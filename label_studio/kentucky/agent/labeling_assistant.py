"""Agentic labeling assistant.

Two real proposal sources (no fabricated AI output):

1. ``ka-geometry-agent`` - deterministic construction-drawing rules over extracted vector primitives and
   the candidate graph (parallel wall-face pairs, door leaf + swing arcs, window glazing lines, room tags,
   schedule-style text keywords). Every proposal carries evidence (rule, primitive ids, measurements).
2. ``ka-model-agent`` - model-in-the-loop: a registered model version predicts on a sheet and the
   predictions become proposals with ``model_version`` provenance.

An optional LLM planner (``agent/llm.py``) can be enabled later; it is disabled until an LLM provider is
configured. Proposals are NEVER ground truth: they stay ``pending`` until a human accepts / edits /
rejects them; accepted proposals keep the original payload and a link to the final object.

Drawing text is treated as untrusted data: it is only matched against keyword tables, never executed or
interpreted as instructions.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

import numpy as np
from django.db import transaction
from django.utils import timezone

from ..graph.builder import build_graph, graph_stats
from ..ingest.pipeline import load_primitives
from ..models import CanonicalObject, Proposal, Provenance, Review, SheetGraph

AGENT = 'ka-geometry-agent'
AGENT_VERSION = '1.0.0'
MODEL_AGENT = 'ka-model-agent'

KEYWORDS = {
    'door': [r'\bDOORS?\b', r'\bDR\b', r'\bDOOR SCHEDULE\b'],
    'window': [r'\bWINDOWS?\b', r'\bGLAZ(ING)?\b', r'\bWDW\b'],
    'room': [r'\b(OFFICE|CONF|CONFERENCE|STORAGE|LOBBY|BREAK|MECH|ELEC|RESTROOM|TOILET|CORRIDOR|IT|OPEN OFFICE)\b'],
    'hvac_equipment': [r'\b(RTU|AHU|VAV|FCU|EF|CUH)[- ]?\d*\b'],
    'diffuser': [r'\b(DIFFUSER|SD|RG|CD|SUPPLY GRILLE|RETURN GRILLE)\b'],
    'duct': [r'\bDUCT(WORK)?\b', r'\b\d+"?X\d+"?\b'],
    'electrical_device': [r'\b(RECEPT(ACLE)?|DUPLEX|GFCI|PANEL|SWITCH)\b'],
    'plumbing_fixture': [r'\b(WC|LAV|SINK|URINAL|FLOOR DRAIN|FD|MOP SINK)\b'],
    'structural_member': [r'\b(COLUMN|BEAM|W\d+X\d+|HSS)\b'],
    'floor_finish': [r'\b(CPT|LVT|VCT|CARPET|TILE|SEALED CONC)\b'],
    'ceiling': [r'\b(ACT|GYP BD CLG|CEILING|CLG)\b'],
}
ROOM_TAG = re.compile(r'^[A-Z][A-Z /&-]{1,30}\s*\d{1,4}[A-Z]?$')


def _prop(dataset, sheet, kind, payload, confidence, evidence, explanation, agent=AGENT, version=AGENT_VERSION, mv=None):
    return Proposal(organization_id=dataset.organization_id, dataset=dataset, sheet=sheet, kind=kind, agent=agent,
                    agent_version=version, model_version=mv, confidence=round(float(confidence), 4), payload=payload,
                    evidence=evidence, explanation=explanation)


# ------------------------------------------------------------------------------------- classes
def suggest_classes(dataset) -> list[Proposal]:
    from ..labeling import current_taxonomy

    tax = current_taxonomy(dataset)
    have = set(tax.names('cv'))
    hits = defaultdict(list)
    for sheet in dataset.sheets.all():
        for p in load_primitives(sheet).get('primitives', []):
            if p['type'] != 'text' or not p.get('text'):
                continue
            t = str(p['text']).upper()[:200]
            for cls, pats in KEYWORDS.items():
                if any(re.search(pt, t) for pt in pats):
                    hits[cls].append({'sheet': sheet.id, 'text': t[:80], 'primitive': p['id']})
    props = []
    for cls, ev in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        props.append(_prop(dataset, None, Proposal.Kind.CLASS_SUGGESTION,
                           {'class': cls, 'already_in_taxonomy': cls in have}, min(0.95, 0.4 + 0.05 * len(ev)),
                           {'rule': 'keyword_match', 'matches': ev[:20], 'count': len(ev)},
                           f'Drawing text mentions {cls.replace("_", " ")} {len(ev)} time(s), e.g. "{ev[0]["text"]}".'))
    Proposal.objects.bulk_create(props)
    return props


# ------------------------------------------------------------------------------------- graph labels
def current_graph(sheet, build_if_missing=True) -> SheetGraph | None:
    g = SheetGraph.objects.filter(sheet=sheet, is_current=True).first()
    if g is None and build_if_missing:
        prims = load_primitives(sheet)['primitives']
        gd = build_graph(prims, (sheet.width, sheet.height))
        g = SheetGraph.objects.create(organization_id=sheet.organization_id, sheet=sheet, version=1, graph=gd,
                                      stats=graph_stats(gd), source='builder', message='candidate graph from geometry')
    return g


def _line_info(n):
    x0, y0, x1, y1 = n['bbox']
    return {'len': math.hypot(x1 - x0, y1 - y0), 'w': x1 - x0, 'h': y1 - y0}


def geometric_node_proposals(graph: dict, image_size) -> list[dict]:
    """Rule-based semantic proposals for primitive nodes. Returns [{node_ids, label, confidence, rule, evidence}]."""
    W, H = image_size
    diag = math.hypot(W, H)
    nodes = {n['id']: n for n in graph['nodes']}
    adj = defaultdict(list)
    for e in graph['edges']:
        adj[e['source']].append((e['target'], e))
        adj[e['target']].append((e['source'], e))
    out = []
    taken = set()
    # doors: curve/arc (quarter swing) touching a straight leaf of ~equal length
    for nid, n in nodes.items():
        if n['type'] not in ('curve', 'arc'):
            continue
        bx = n['bbox']
        w, h = bx[2] - bx[0], bx[3] - bx[1]
        if min(w, h) <= 0 or not (0.75 < w / h < 1.33):
            continue
        r = (w + h) / 2
        leaf = None
        for m, e in adj[nid]:
            mn = nodes[m]
            if mn['type'] == 'line' and e['type'] in ('connects_to', 'intersects') and abs(_line_info(mn)['len'] - r) < 0.2 * r:
                leaf = m
                break
        if leaf:
            out.append({'node_ids': [nid, leaf], 'label': 'door', 'confidence': 0.86, 'rule': 'door_swing_arc_plus_leaf',
                        'evidence': {'arc': nid, 'leaf': leaf, 'radius_px': round(r, 1)}, 'group': True})
            taken |= {nid, leaf}
    # windows: >=3 short, thin, mutually parallel lines (glazing) of equal length
    par = defaultdict(set)
    for e in graph['edges']:
        if e['type'] == 'parallel_near':
            par[e['source']].add(e['target'])
            par[e['target']].add(e['source'])
    widths = [float(n['features'][12]) for n in nodes.values() if n['type'] == 'line']
    wall_w = np.percentile(widths, 75) if widths else 0
    for nid, n in nodes.items():
        if nid in taken or n['type'] != 'line' or nid not in par:
            continue
        L = _line_info(n)['len']
        grp = {nid} | {m for m in par[nid] if abs(_line_info(nodes[m])['len'] - L) < 0.1 * L and m not in taken}
        if len(grp) >= 3 and L < 0.06 * diag and float(n['features'][12]) < wall_w:
            out.append({'node_ids': sorted(grp), 'label': 'window', 'confidence': 0.74, 'rule': 'parallel_thin_glazing_lines',
                        'evidence': {'lines': sorted(grp), 'length_px': round(L, 1)}, 'group': True})
            taken |= grp
    # walls: long parallel face pairs, plus short perpendicular end caps between two wall faces
    for nid, n in nodes.items():
        if nid in taken or n['type'] != 'line':
            continue
        partners = [m for m in par.get(nid, ()) if m not in taken and nodes[m]['type'] == 'line']
        if partners:
            m = max(partners, key=lambda k: _line_info(nodes[k])['len'])
            out.append({'node_ids': sorted({nid, m}), 'label': 'wall', 'confidence': 0.78, 'rule': 'parallel_face_pair',
                        'evidence': {'faces': [nid, m]}, 'group': True})
            taken |= {nid, m}
    wall_nodes = {i for o in out if o['label'] == 'wall' for i in o['node_ids']}
    for nid, n in nodes.items():
        if nid in taken or n['type'] != 'line':
            continue
        touching = [m for m, e in adj[nid] if m in wall_nodes and e['type'] == 'connects_to' and e['features'][8] > 0]
        if len(touching) >= 2 and _line_info(n)['len'] < 0.02 * diag:
            out.append({'node_ids': [nid], 'label': 'wall', 'confidence': 0.62, 'rule': 'wall_end_cap',
                        'evidence': {'caps': touching[:2]}, 'group': False})
            taken.add(nid)
    for nid, n in nodes.items():
        if n['type'] == 'text' and n.get('text') and ROOM_TAG.match(str(n['text']).strip().upper()):
            out.append({'node_ids': [nid], 'label': 'room_tag', 'confidence': 0.8, 'rule': 'room_tag_pattern',
                        'evidence': {'text': str(n['text'])[:60]}, 'group': False})
    return out


@transaction.atomic
def propose_graph(sheet, dataset) -> tuple[SheetGraph, list[Proposal]]:
    """Run geometry rules; store each suggestion as a Proposal (pending). Graph is not modified."""
    g = current_graph(sheet)
    suggestions = geometric_node_proposals(g.graph, (sheet.width, sheet.height))
    props = [_prop(dataset, sheet, Proposal.Kind.GROUP if s['group'] else Proposal.Kind.NODE_LABEL,
                   {'graph_version_id': g.id, 'node_ids': s['node_ids'], 'label': s['label'], 'group': s['group']},
                   s['confidence'], {'rule': s['rule'], **s['evidence']},
                   f'{s["rule"].replace("_", " ")} -> {s["label"]}') for s in suggestions]
    Proposal.objects.bulk_create(props)
    return g, props


def apply_graph_proposals(sheet, proposals, user, accept=True, min_confidence=0.0) -> SheetGraph:
    """Accept (or reject) graph proposals into a NEW graph version. Accepted items are marked
    provenance=agent_accepted, review=approved, with the proposal id recorded on the node."""
    g = current_graph(sheet)
    data = {**g.graph, 'nodes': [dict(n) for n in g.graph['nodes']], 'edges': [dict(e) for e in g.graph['edges']]}
    by_id = {n['id']: n for n in data['nodes']}
    edge_ix = {}
    for e in data['edges']:
        edge_ix[(e['source'], e['target'])] = e
        edge_ix[(e['target'], e['source'])] = e
    now = timezone.now()
    for p in proposals:
        if p.status != Proposal.Status.PENDING:
            continue
        if not accept or (p.confidence or 0) < min_confidence:
            if not accept:
                p.status, p.reviewed_by, p.reviewed_at = Proposal.Status.REJECTED, user, now
                p.save()
            continue
        pl = getattr(p, '_override', None) or p.payload  # human-modified proposal, original payload untouched
        ids = [i for i in pl['node_ids'] if i in by_id]
        obj_uid = f'grp_{p.id}' if pl.get('group') else None
        for i in ids:
            n = by_id[i]
            n.update({'label': pl['label'], 'provenance': Provenance.AGENT_ACCEPTED, 'review': 'approved',
                      'confidence': p.confidence, 'proposal_id': p.id})
            if obj_uid:
                n['object_uid'] = obj_uid
        if obj_uid:
            for a in ids:
                for b in ids:
                    if a < b and (a, b) in edge_ix:
                        e = edge_ix[(a, b)]
                        e.update({'label': 'same_object', 'provenance': Provenance.AGENT_ACCEPTED, 'review': 'approved',
                                  'proposal_id': p.id})
        p.status, p.reviewed_by, p.reviewed_at = Proposal.Status.ACCEPTED, user, now
        p.final_payload = {'node_ids': ids, 'label': pl['label'], 'object_uid': obj_uid}
        p.save()
    return save_graph_version(sheet, data, user, source='agent_accepted', message=f'applied {len(proposals)} proposals', parent=g)


def save_graph_version(sheet, data, user, source='human', message='', parent=None) -> SheetGraph:
    cur = SheetGraph.objects.select_for_update().filter(sheet=sheet).order_by('-version').first()
    SheetGraph.objects.filter(sheet=sheet, is_current=True).update(is_current=False)
    return SheetGraph.objects.create(organization_id=sheet.organization_id, sheet=sheet, version=(cur.version + 1 if cur else 1),
                                     graph=data, stats=graph_stats(data), source=source, parent=parent or cur,
                                     created_by=user if (user and user.is_authenticated) else None, message=message[:500])


# ------------------------------------------------------------------------------------- CV proposals
def propose_cv_from_graph(sheet, dataset, labels=('wall', 'door', 'window')) -> list[Proposal]:
    """Turn geometric groups into tight polygon proposals for CV labeling (pushed to LS as predictions)."""
    from shapely.geometry import MultiPoint

    from ..labeling import push_proposal_to_label_studio

    g = current_graph(sheet)
    nodes = {n['id']: n for n in g.graph['nodes']}
    prims = {p['id']: p for p in load_primitives(sheet)['primitives']}
    groups = [s for s in geometric_node_proposals(g.graph, (sheet.width, sheet.height)) if s['label'] in labels]
    props = []
    for s in groups:
        pts = [pt for i in s['node_ids'] for pt in prims[i]['pts_px'] if i in prims]
        if len(pts) < 3:
            continue
        hull = MultiPoint(pts).minimum_rotated_rectangle if s['label'] == 'wall' else MultiPoint(pts).envelope
        if hull.geom_type != 'Polygon' or hull.area < 4:
            continue
        poly = [list(map(float, c)) for c in list(hull.exterior.coords)[:-1]]
        props.append(_prop(dataset, sheet, Proposal.Kind.CV_OBJECT, {'label': s['label'], 'polygon': poly, 'primitive_ids': s['node_ids']},
                           s['confidence'] * 0.95, {'rule': s['rule'], 'from_graph_version': g.id, 'nodes': s['node_ids'][:20]},
                           f'Polygon around {len(s["node_ids"])} primitives matched by {s["rule"]}.'))
    Proposal.objects.bulk_create(props)
    for p in Proposal.objects.filter(sheet=sheet, kind=Proposal.Kind.CV_OBJECT, agent=AGENT, ls_prediction_id=None, status='pending'):
        push_proposal_to_label_studio(p)
    return props


def propose_from_model(sheet, dataset, model_version, labels=None) -> list[Proposal]:
    """Model-in-the-loop proposals. ``labels`` limits them to the item types this model is chosen for."""
    from ..inference.predictors import predict
    from ..labeling import push_proposal_to_label_studio

    res = predict(model_version, {'sheet_id': sheet.id}, sheet.organization_id)
    props = []
    if res['task'] in ('semantic_segmentation', 'instance_segmentation'):
        from ..coords import clean_polygon

        for p in res['predictions']:
            if labels is not None and p['label'] not in labels:
                continue
            poly = clean_polygon(p.get('polygon'), sheet.width, sheet.height)
            if poly is None:
                continue
            props.append(_prop(dataset, sheet, Proposal.Kind.CV_OBJECT, {'label': p['label'], 'polygon': poly}, p['confidence'],
                               {'model_version': model_version.id, 'task': res['task']},
                               f'Predicted by {model_version.model.name} v{model_version.version}', agent=MODEL_AGENT,
                               version=f'{model_version.model.name}:v{model_version.version}', mv=model_version))
        Proposal.objects.bulk_create(props)
        for p in Proposal.objects.filter(sheet=sheet, agent=MODEL_AGENT, ls_prediction_id=None, status='pending', kind='cv_object'):
            push_proposal_to_label_studio(p)
    else:
        g = current_graph(sheet)
        for n in res.get('nodes', []):
            probs = sorted(n['probabilities'].values(), reverse=True)
            margin = probs[0] - (probs[1] if len(probs) > 1 else 0)
            props.append(_prop(dataset, sheet, Proposal.Kind.NODE_LABEL,
                               {'graph_version_id': g.id, 'node_ids': [n['id']], 'label': n['label'], 'group': False}, n['confidence'],
                               {'model_version': model_version.id, 'margin': round(margin, 4), 'probabilities': n['probabilities']},
                               explain_uncertainty(n['probabilities'], sheet), agent=MODEL_AGENT,
                               version=f'{model_version.model.name}:v{model_version.version}', mv=model_version))
        Proposal.objects.bulk_create(props)
    return props


def explain_uncertainty(probs: dict, sheet=None) -> str:
    top = sorted(probs.items(), key=lambda kv: -kv[1])
    reasons = []
    if len(top) > 1 and top[0][1] - top[1][1] < 0.2:
        reasons.append(f'close call between {top[0][0]} ({top[0][1]:.2f}) and {top[1][0]} ({top[1][1]:.2f})')
    if top[0][1] < 0.5:
        reasons.append('low top-class probability')
    if sheet is not None and not sheet.has_vector:
        reasons.append('input lines were raster-inferred from a scan, not native vectors')
    return ('Uncertain: ' + '; '.join(reasons)) if reasons else f'Confident {top[0][0]} ({top[0][1]:.2f})'


# ------------------------------------------------------------------------------------- QA agent
def quality_review(dataset) -> list[Proposal]:
    """Flag possibly incorrect / missing / conflicting annotations as QUALITY_FLAG proposals."""
    from shapely.geometry import Polygon

    from ..datasets.quality import polygon_issues

    flags = []
    for sheet in dataset.sheets.all():
        objs = list(CanonicalObject.objects.filter(sheet=sheet, deleted=False, is_negative=False).exclude(review_status=Review.REJECTED))
        geo = {}
        for o in objs:
            poly = o.geometry.get('polygon')
            if o.geometry_type in ('polygon', 'bbox'):
                iss = polygon_issues(poly, sheet.width, sheet.height)
                if iss:
                    flags.append(_prop(dataset, sheet, Proposal.Kind.QUALITY_FLAG, {'object': o.uid, 'issue': 'invalid_geometry', 'details': iss},
                                       0.99, {'rule': 'polygon_validity'}, f'{o.label} {o.uid}: {", ".join(iss)}'))
                    continue
            if poly and len(poly) >= 3:
                geo[o.uid] = (o, Polygon(poly).buffer(0))
        # suspected label errors: agent geometry disagrees with human label on strong overlap
        if sheet.has_vector:
            g = current_graph(sheet)
            prims = {p['id']: p for p in load_primitives(sheet)['primitives']}
            for s in geometric_node_proposals(g.graph, (sheet.width, sheet.height)):
                if s['label'] not in ('door', 'window', 'wall') or s['confidence'] < 0.7:
                    continue
                pts = [pt for i in s['node_ids'] for pt in prims.get(i, {}).get('pts_px', [])]
                if len(pts) < 3:
                    continue
                from shapely.geometry import MultiPoint

                env = MultiPoint(pts).envelope.buffer(1)
                covered = [(o, p) for o, p in geo.values() if p.intersects(env) and p.intersection(env).area > 0.5 * env.area]
                if not covered and objs:
                    flags.append(_prop(dataset, sheet, Proposal.Kind.QUALITY_FLAG,
                                       {'issue': 'possible_missing_object', 'label': s['label'], 'bbox': list(env.bounds)},
                                       s['confidence'] * 0.8, {'rule': s['rule'], 'nodes': s['node_ids'][:10]},
                                       f'Geometry looks like a {s["label"]} ({s["rule"]}) but no annotation covers it.'))
                for o, _ in covered:
                    if o.label != s['label'] and o.label != 'unknown' and s['label'] != 'wall':
                        flags.append(_prop(dataset, sheet, Proposal.Kind.QUALITY_FLAG,
                                           {'object': o.uid, 'issue': 'possible_wrong_label', 'annotated': o.label, 'suggested': s['label']},
                                           s['confidence'] * 0.7, {'rule': s['rule']},
                                           f'Annotated as {o.label} but geometry matches {s["label"]} ({s["rule"]}).'))
    Proposal.objects.bulk_create(flags)
    return flags


def dataset_summary(dataset) -> dict:
    from ..datasets.quality import readiness
    from ..labeling import current_taxonomy

    rep = readiness(dataset, current_taxonomy(dataset))
    st = rep['stats']
    recs = []
    for c, n in sorted(st['class_counts'].items(), key=lambda kv: kv[1]):
        if n < 10:
            recs.append(f'Add more "{c}" examples (only {n} approved); aim for >= 30 across several buildings.')
    if st['raster_sheets'] == 0:
        recs.append('No scanned sheets: add scans if the model must work on raster plans (performance does not transfer automatically).')
    if st['vector_sheets'] == 0:
        recs.append('No vector sheets: graph (GNN) training needs native vector PDFs or DXF.')
    if st['pending']:
        recs.append(f'Review {st["pending"]} pending objects - unreviewed annotations are excluded from training.')
    groups = {s.document.split_group for s in dataset.sheets.select_related('document')}
    if len(groups) < 3:
        recs.append(f'Only {len(groups)} building/project group(s): test metrics will not reflect performance on unfamiliar buildings.')
    pending_props = Proposal.objects.filter(dataset=dataset, status='pending').count()
    return {'readiness': rep, 'recommendations': recs, 'pending_proposals': pending_props, 'generated_by': f'{AGENT}@{AGENT_VERSION} (rule-based)'}


# ------------------------------------------------------------------------------------- find more like this
SIMILAR_AGENT, SIMILAR_VERSION = 'ka-similar-symbols', '1.0.0'


def find_similar(sheet, dataset, polygon, label, threshold=0.85, max_results=200) -> list[Proposal]:
    """'Find more like this': the item the user marked becomes a template; normalized cross-correlation of the INK
    (inverted image, so blank paper never matches) over the sheet in all 8 orientations (4 rotations x mirror), plus an
    ink-amount check, finds repeats of the same symbol (doors, windows, fixtures, devices). Works the same on vector
    renders and scans; no model, no GPU, no third-party weights. Threshold tuned on labeled scans + vectors:
    83% of repeats found with 0 wrong matches (docs/kentucky/TEST_RESULTS.md)."""
    import io

    import cv2
    from PIL import Image

    from .. import storage
    from ..coords import clean_polygon
    from ..labeling import push_proposal_to_label_studio

    img = np.asarray(Image.open(io.BytesIO(storage.get_bytes(sheet.image_key, sheet.organization_id))).convert('L'), dtype=np.float32)
    H, W = img.shape
    p = np.asarray(polygon, dtype=float)
    x0, y0 = np.floor(p.min(0)).astype(int)
    x1, y1 = np.ceil(p.max(0)).astype(int)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        raise ValueError('The marked item is too small to search for.')
    # work at a resolution where the template is ~48 px: fast and tolerant to scan noise
    s = min(1.0, 48.0 / max(x1 - x0, y1 - y0))
    small = cv2.resize(255.0 - img, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA)  # ink
    tpl = small[int(y0 * s):max(int(y1 * s), int(y0 * s) + 2), int(x0 * s):max(int(x1 * s), int(x0 * s) + 2)]
    tink = float(tpl.mean())
    if tpl.std() < 1e-3 or tink < 2:
        raise ValueError('The marked area is blank — mark the symbol itself.')
    cands = []
    for flip in (False, True):
        t0 = tpl[:, ::-1] if flip else tpl
        for k in range(4):
            t = np.ascontiguousarray(np.rot90(t0, k))
            if t.shape[0] >= small.shape[0] or t.shape[1] >= small.shape[1]:
                continue
            r = cv2.matchTemplate(small, t, cv2.TM_CCORR_NORMED)
            ys, xs = np.nonzero(r >= threshold)
            for y, x in zip(ys, xs):
                ratio = float(small[y:y + t.shape[0], x:x + t.shape[1]].mean()) / tink
                if 0.6 < ratio < 1.6:  # about as much linework as the marked symbol
                    cands.append((float(r[y, x]), x / s, y / s, t.shape[1] / s, t.shape[0] / s, k, flip))
    cands.sort(key=lambda c: -c[0])
    kept, boxes = [], [(x0, y0, x1, y1)]  # never re-propose the item the user marked

    def overlaps(b):
        for o in boxes:
            iw = max(0, min(b[2], o[2]) - max(b[0], o[0]))
            ih = max(0, min(b[3], o[3]) - max(b[1], o[1]))
            if iw * ih > 0.3 * min((b[2] - b[0]) * (b[3] - b[1]), (o[2] - o[0]) * (o[3] - o[1])):
                return True
        return False

    for sc, x, y, w, h, k, flip in cands:
        b = (x, y, x + w, y + h)
        if overlaps(b):
            continue
        boxes.append(b)
        kept.append((sc, b, k, flip))
        if len(kept) >= max_results:
            break
    props = []
    for sc, (bx0, by0, bx1, by1), k, flip in kept:
        poly = clean_polygon([[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1]], W, H)
        if poly is None:
            continue
        props.append(_prop(dataset, sheet, Proposal.Kind.CV_OBJECT, {'label': label, 'polygon': poly}, float(sc),
                           {'method': 'template_ncc', 'orientation': int(k) * 90, 'mirrored': bool(flip), 'template_box': [int(x0), int(y0), int(x1), int(y1)]},
                           f'Looks like the {label} you marked (match {sc:.2f}).', agent=SIMILAR_AGENT, version=SIMILAR_VERSION))
    Proposal.objects.bulk_create(props)
    for pr in Proposal.objects.filter(sheet=sheet, agent=SIMILAR_AGENT, ls_prediction_id=None, status='pending'):
        push_proposal_to_label_studio(pr)
    return props
