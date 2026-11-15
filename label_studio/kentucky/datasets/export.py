"""Dataset version exports.

Bundle layout (directory, also zipped into storage):

    manifest.json        dataset version manifest + taxonomy + splits
    images/<sheet>.png   annotation-ready sheet renders
    coco/{split}.json    COCO detection + instance segmentation (polygons / uncompressed RLE)
    semantic/<sheet>.png uint8 class-index masks (0 = background) + semantic/classes.json
    graphs/<sheet>.json  graph JSON (canonical schema)
    pyg/{split}.pt       list[torch_geometric.data.Data] (node + edge classification)
    pyg/meta.json        feature spec + label maps

The same bundle is what training workers (local or cloud GPU) consume, so training never reads
the application database.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .. import storage
from ..graph.builder import EDGE_DIM, FEATURE_SPEC, NODE_DIM
from ..models import SheetGraph
from ..training.rle import rle_decode, rle_encode  # noqa: F401
from .quality import is_verified

FORMATS = ['coco', 'semantic', 'graph_json', 'pyg']


def cv_classes(version):
    """Taxonomy CV classes that have at least one approved example in this version (others cannot be learned)."""
    present = {o['label'] for o in version.manifest['objects'] if not o.get('is_negative')}
    return [c['name'] for c in version.taxonomy['classes'] if c['kind'] == 'cv' and c['name'] != 'unknown' and c['name'] in present]


def node_classes(version):
    return [c['name'] for c in version.taxonomy['classes'] if c['kind'] == 'node']


def edge_classes(version):
    return [c['name'] for c in version.taxonomy['classes'] if c['kind'] == 'edge']


def split_of(version):
    m = {}
    for k in ('train', 'val', 'test'):
        for sid in version.splits[k]:
            m[sid] = k
    return m


def _mask_from_object(o, W, H):
    g = o['geometry']
    if o['geometry_type'] == 'mask' and g.get('mask_rle_ls'):
        from label_studio_sdk.converter.brush import decode_rle

        flat = decode_rle(g['mask_rle_ls'])
        h, w = g.get('size', [H, W])
        return np.reshape(flat, (h, w, 4))[:, :, 3] > 0
    if g.get('polygon'):
        im = Image.new('L', (W, H), 0)
        ImageDraw.Draw(im).polygon([tuple(p) for p in g['polygon']], fill=1)
        return np.asarray(im) > 0
    return None


def export_version(version, out_dir: str | Path, formats=None) -> Path:
    formats = formats or FORMATS
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / 'images').mkdir(parents=True)
    org = version.organization_id
    sheets = {s['id']: s for s in version.manifest['sheets']}
    splits = split_of(version)
    for sid, s in sheets.items():
        (out / 'images' / f'{sid}.png').write_bytes(storage.get_bytes(s['image_key'], org))
    meta = {
        'dataset_id': version.dataset_id, 'dataset_version': version.version, 'version_id': version.id,
        'content_hash': version.content_hash, 'taxonomy': version.taxonomy, 'splits': version.splits,
        'sheets': version.manifest['sheets'], 'negative_sheets': version.manifest.get('negative_sheets', []),
        'formats': formats, 'cv_classes': cv_classes(version),
    }
    (out / 'manifest.json').write_text(json.dumps(meta, indent=1))
    classes = cv_classes(version)
    objs = [o for o in version.manifest['objects'] if not o.get('is_negative') and o['label'] in classes]

    if 'coco' in formats:
        (out / 'coco').mkdir()
        cats = [{'id': i + 1, 'name': c, 'supercategory': 'construction'} for i, c in enumerate(classes)]
        for split in ('train', 'val', 'test'):
            ids = [sid for sid in sheets if splits.get(sid) == split]
            coco = {'info': {'description': 'Kentucky AI dataset export', 'version': version.version, 'content_hash': version.content_hash},
                    'images': [], 'annotations': [], 'categories': cats}
            for sid in ids:
                s = sheets[sid]
                coco['images'].append({'id': sid, 'file_name': f'images/{sid}.png', 'width': s['width'], 'height': s['height'],
                                       'ka_has_vector': s['has_vector']})
            aid = 0
            for o in objs:
                if splits.get(o['sheet_id']) != split:
                    continue
                s = sheets[o['sheet_id']]
                aid += 1
                ann = {'id': aid, 'image_id': o['sheet_id'], 'category_id': classes.index(o['label']) + 1, 'iscrowd': 0,
                       'ka_uid': o['uid'], 'ka_provenance': o['provenance']}
                if o['geometry_type'] == 'mask':
                    m = _mask_from_object(o, s['width'], s['height'])
                    ys, xs = np.nonzero(m)
                    ann['segmentation'] = rle_encode(m)
                    ann['bbox'] = [float(xs.min()), float(ys.min()), float(np.ptp(xs) + 1), float(np.ptp(ys) + 1)]
                    ann['area'] = float(m.sum())
                elif o['geometry'].get('polygon'):
                    from shapely.geometry import Polygon

                    poly = o['geometry']['polygon']
                    ann['segmentation'] = [[round(float(v), 3) for p in poly for v in p]]
                    ann['bbox'] = [round(float(v), 3) for v in o['bbox']]
                    ann['area'] = float(Polygon(poly).area)
                else:
                    continue
                coco['annotations'].append(ann)
            (out / 'coco' / f'{split}.json').write_text(json.dumps(coco))

    if 'semantic' in formats:
        (out / 'semantic').mkdir()
        (out / 'semantic' / 'classes.json').write_text(json.dumps({'0': '__background__', **{str(i + 1): c for i, c in enumerate(classes)}}))
        for sid, s in sheets.items():
            sem = np.zeros((s['height'], s['width']), dtype=np.uint8)
            # draw larger objects first so small objects (doors, windows) stay visible on top
            mine = sorted([o for o in objs if o['sheet_id'] == sid], key=lambda o: -(o['bbox'][2] * o['bbox'][3] if o.get('bbox') else 0))
            for o in mine:
                m = _mask_from_object(o, s['width'], s['height'])
                if m is not None:
                    sem[m] = classes.index(o['label']) + 1
            Image.fromarray(sem).save(out / 'semantic' / f'{sid}.png')

    if 'graph_json' in formats or 'pyg' in formats:
        (out / 'graphs').mkdir()
        gids = {g['sheet_id']: g['graph_version_id'] for g in version.manifest['graphs']}
        graphs = {g.sheet_id: g.graph for g in SheetGraph.objects.filter(id__in=gids.values())}
        for sid, g in graphs.items():
            (out / 'graphs' / f'{sid}.json').write_text(json.dumps(g))
        if 'pyg' in formats:
            export_pyg(version, graphs, out / 'pyg', splits)
    return out


def graph_to_pyg(g: dict, ncls: list[str], ecls: list[str], sheet_id=None, require_verified=True):
    import torch
    from torch_geometric.data import Data

    from ..graph.builder import EDGE_TYPES

    idx = {n['id']: i for i, n in enumerate(g['nodes'])}
    x = torch.tensor([n['features'] for n in g['nodes']], dtype=torch.float32).reshape(-1, NODE_DIM)
    y = torch.full((len(g['nodes']),), -1, dtype=torch.long)
    for i, n in enumerate(g['nodes']):
        if n.get('label') in ncls and (is_verified(n) or not require_verified):
            y[i] = ncls.index(n['label'])
    src, dst, ea, ey, et = [], [], [], [], []
    for e in g['edges']:
        if e['source'] not in idx or e['target'] not in idx:
            continue
        a, b = idx[e['source']], idx[e['target']]
        lab = -1
        if e.get('label') in ecls and (is_verified(e) or not require_verified):
            lab = ecls.index(e['label'])
        t = EDGE_TYPES.index(e['type']) if e['type'] in EDGE_TYPES else 0
        for u, v in ((a, b), (b, a)) if not e.get('directed') else ((a, b),):
            src.append(u)
            dst.append(v)
            ea.append(e['features'])
            ey.append(lab)
            et.append(t)
    data = Data(
        x=x,
        edge_index=torch.tensor([src, dst], dtype=torch.long).reshape(2, -1),
        edge_attr=torch.tensor(ea, dtype=torch.float32).reshape(-1, EDGE_DIM),
        y=y,
        edge_y=torch.tensor(ey, dtype=torch.long),
        edge_type=torch.tensor(et, dtype=torch.long),
    )
    data.sheet_id = sheet_id
    data.node_ids = [n['id'] for n in g['nodes']]
    return data


def export_pyg(version, graphs, out: Path, splits):
    import torch

    out.mkdir(parents=True, exist_ok=True)
    ncls, ecls = node_classes(version), edge_classes(version)
    for split in ('train', 'val', 'test'):
        items = [graph_to_pyg(g, ncls, ecls, sid) for sid, g in sorted(graphs.items()) if splits.get(sid) == split]
        torch.save(items, out / f'{split}.pt')
    (out / 'meta.json').write_text(json.dumps({'feature_spec': FEATURE_SPEC, 'node_classes': ncls, 'edge_classes': ecls,
                                               'node_dim': NODE_DIM, 'edge_dim': EDGE_DIM}))


def store_export(version, out_dir: Path) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(out_dir):
            for f in files:
                p = Path(root) / f
                zf.write(p, p.relative_to(out_dir).as_posix())
    k = storage.key(version.organization_id, 'datasets', version.dataset_id, 'versions', version.version, 'export.zip')
    storage.put_bytes(k, buf.getvalue())
    version.export_key = k
    version.export_formats = FORMATS
    version.save(update_fields=['export_key', 'export_formats'])
    return k
