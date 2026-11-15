"""Model loading + inference for deployed model versions.

Preprocessing mirrors training exactly (``training.cv.to_input`` and ``training_scale``; graph features
from ``graph.builder`` with the same FEATURE_SPEC version). Outputs are mapped back to sheet image
pixels and, when a sheet is given, to the original source coordinates (PDF points / CAD units).
"""

from __future__ import annotations

import base64
import hashlib
import io
import threading
from collections import OrderedDict

import numpy as np
from PIL import Image

from .. import coords, storage

_CACHE: OrderedDict = OrderedDict()
_LOCK = threading.Lock()
MAX_CACHED = 8


class InferenceError(ValueError):
    pass


def _box_model(ck) -> bool:
    from ..training.rtdetr import SPECS

    return ck.get('catalog_id') in SPECS


def load_checkpoint(mv):
    import torch

    ck_key = (mv.id, mv.artifact_sha256)  # sha in the key: a cache entry can never serve different weights
    with _LOCK:
        if ck_key in _CACHE:
            _CACHE.move_to_end(ck_key)
            return _CACHE[ck_key]
    raw = storage.get_bytes(mv.artifact_key, mv.organization_id)
    if hashlib.sha256(raw).hexdigest() != mv.artifact_sha256:
        raise InferenceError('Model artifact failed integrity check')
    ck = torch.load(io.BytesIO(raw), map_location='cpu', weights_only=False)
    task = ck['task']
    if task == 'semantic_segmentation':
        from ..training.cv import build_semantic

        model = build_semantic(ck['catalog_id'], len(ck['classes']) + 1, 'scratch')
    elif task == 'instance_segmentation':
        from ..training.cv import build_maskrcnn

        model = build_maskrcnn(ck['catalog_id'], len(ck['classes']) + 1, 'scratch')
    else:
        from ..training.gnn import load_model

        model = load_model(ck)
    if task in ('semantic_segmentation', 'instance_segmentation'):
        model.load_state_dict(ck['state_dict'])
        model.eval()
    with _LOCK:
        _CACHE[ck_key] = (model, ck)
        while len(_CACHE) > MAX_CACHED:
            _CACHE.popitem(last=False)
    return model, ck


def _gray_from_input(payload, org_id):
    """Returns (gray float32 at sheet-image resolution, sheet or None)."""
    from ..models import Sheet

    if payload.get('sheet_id') is not None:
        sheet = Sheet.objects.filter(id=payload['sheet_id'], organization_id=org_id).first()
        if sheet is None:
            raise InferenceError('sheet not found')
        im = Image.open(io.BytesIO(storage.get_bytes(sheet.image_key, org_id))).convert('L')
        return np.asarray(im, dtype=np.float32) / 255.0, sheet
    if payload.get('image'):
        try:
            raw = base64.b64decode(payload['image'], validate=True)
        except Exception:  # noqa: BLE001
            raise InferenceError('image must be base64')
        if len(raw) > 30 * 1024 * 1024:
            raise InferenceError('image too large (30 MB max)')
        if not (raw.startswith(b'\x89PNG') or raw.startswith(b'\xff\xd8')):
            raise InferenceError('image must be PNG or JPEG')
        im = Image.open(io.BytesIO(raw))
        im.load()
        if im.width * im.height > 60_000_000:
            raise InferenceError('image too large')
        return np.asarray(im.convert('L'), dtype=np.float32) / 255.0, None
    raise InferenceError('provide "sheet_id" or base64 "image"')


def _resize(gray, s):
    if s == 1.0:
        return gray
    im = Image.fromarray((gray * 255).astype(np.uint8))
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def _polys_from_mask(mask, min_area=6):
    import cv2

    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        if cv2.contourArea(c) < min_area:
            continue
        eps = 0.5
        approx = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(approx) >= 3:
            out.append(approx.astype(float))
    return out


def _with_coords(poly_train, s, sheet, page):
    poly_img = (np.asarray(poly_train, dtype=float) / s)
    x0, y0 = poly_img.min(0)
    x1, y1 = poly_img.max(0)
    d = {'polygon': poly_img.round(2).tolist(), 'bbox': [round(float(x0), 2), round(float(y0), 2),
                                                         round(float(x1 - x0), 2), round(float(y1 - y0), 2)], 'page': page}
    if sheet is not None:
        frame = coords.SheetFrame(sheet.source_to_image, sheet.width, sheet.height)
        d['polygon_source'] = frame.image_to_source(poly_img).round(4).tolist()
        d['source_units'] = sheet.source_units
    return d


def predict(mv, payload: dict, org_id: int) -> dict:
    model, ck = load_checkpoint(mv)
    task = ck['task']
    classes = ck['classes']
    if task in ('semantic_segmentation', 'instance_segmentation'):
        gray, sheet = _gray_from_input(payload, org_id)
        s = float(ck['preprocess'].get('training_scale', 1.0))
        g = _resize(gray, s)
        page = sheet.page_index if sheet else 0
        preds = []
        if task == 'semantic_segmentation':
            from ..training.cv import predict_semantic

            cls, conf = predict_semantic(model, ck['catalog_id'], g)
            for i, c in enumerate(classes, start=1):
                m = cls == i
                if not m.any():
                    continue
                for poly in _polys_from_mask(m):
                    import cv2

                    pm = np.zeros(m.shape, np.uint8)
                    cv2.fillPoly(pm, [poly.astype(np.int32)], 1)
                    sel = (pm > 0) & m
                    preds.append({'label': c, 'confidence': round(float(conf[sel].mean()) if sel.any() else 0.0, 4),
                                  **_with_coords(poly, s, sheet, page)})
        else:
            from ..training.cv import predict_instances

            thr = float(payload.get('score_threshold', ck['config'].get('score_threshold', 0.5)))
            for r in predict_instances(model, g, thr, classes, tile=ck['config'].get('crop_size'), with_masks=False if _box_model(ck) else True):
                if r.get('polygon'):
                    poly = np.asarray(r['polygon'], dtype=float)
                else:
                    polys = _polys_from_mask(r['mask'])
                    if not polys:
                        continue
                    poly = max(polys, key=lambda p: len(p))
                preds.append({'label': r['label'], 'confidence': round(r['score'], 4), **_with_coords(poly, s, sheet, page)})
        return {'task': task, 'model_version': mv.id, 'image_size': [gray.shape[1], gray.shape[0]],
                'sheet_id': sheet.id if sheet else None, 'predictions': preds}
    # graph tasks
    import torch

    from ..datasets.export import graph_to_pyg
    from ..graph.builder import COMPATIBLE_SPECS, FEATURE_SPEC, build_graph

    if payload.get('graph'):
        g = payload['graph']
        if g.get('feature_spec') and g['feature_spec'] not in COMPATIBLE_SPECS:
            raise InferenceError(f'graph feature_spec {g["feature_spec"]} is not supported (expected {FEATURE_SPEC["version"]})')
        sheet = None
    elif payload.get('sheet_id') is not None:
        from ..ingest.pipeline import load_primitives
        from ..models import Sheet

        sheet = Sheet.objects.filter(id=payload['sheet_id'], organization_id=org_id).first()
        if sheet is None:
            raise InferenceError('sheet not found')
        if not sheet.has_vector and not payload.get('allow_raster_inferred'):
            raise InferenceError('sheet has no native vectors; pass allow_raster_inferred=true to use raster-inferred lines')
        g = build_graph(load_primitives(sheet)['primitives'], (sheet.width, sheet.height))
    else:
        raise InferenceError('provide "graph" or "sheet_id"')
    if len(g.get('nodes', [])) > 200_000:
        raise InferenceError('graph too large')
    data = graph_to_pyg(g, [], [], require_verified=False)
    data.x = data.x[:, :int((ck.get('graph_meta') or {}).get('node_dim', data.x.shape[1]))]  # models trained before style features read the first columns only
    with torch.no_grad():
        logits = model(data)
        prob = torch.softmax(logits, -1)
        conf, cls = prob.max(-1)
    if task == 'node_classification':
        nodes = [{'id': n['id'], 'label': classes[int(cls[i])], 'confidence': round(float(conf[i]), 4),
                  'probabilities': {c: round(float(prob[i, j]), 4) for j, c in enumerate(classes)},
                  'primitive_ids': n.get('primitive_ids', [n['id']]), 'bbox': n.get('bbox')} for i, n in enumerate(g['nodes'])]
        out = {'task': task, 'model_version': mv.id, 'sheet_id': sheet.id if sheet else None, 'nodes': nodes}
        if payload.get('takeoff') and sheet is not None:  # quantities from the predicted labels
            from ..api import _takeoff_for

            labels = {pid: n['label'] for n in nodes for pid in n['primitive_ids']}
            out['takeoff'] = _takeoff_for(sheet, labels, payload.get('feet_per_unit'))
        return out
    # edge classification: PyG export duplicates undirected edges (u->v, v->u); average both directions
    edges = []
    k = 0
    for e in g['edges']:
        reps = 1 if e.get('directed') else 2
        p = prob[k:k + reps].mean(0)
        k += reps
        j = int(p.argmax())
        edges.append({'id': e['id'], 'source': e['source'], 'target': e['target'], 'candidate_type': e['type'],
                      'label': classes[j], 'confidence': round(float(p[j]), 4),
                      'probabilities': {c: round(float(p[i]), 4) for i, c in enumerate(classes)}})
    return {'task': task, 'model_version': mv.id, 'sheet_id': sheet.id if sheet else None, 'edges': edges}
