"""Candidate graph construction from vector primitives.

Nodes are primitives (lines, arcs, curves, polylines, rects, circles, text). Edges are *geometric
candidates* (provenance ``geometric``, review ``pending``): they say "these primitives touch / cross /
run parallel / are near" — NOT that a semantic relationship is verified. Annotators then assign
relation labels (``same_object``, ``hosted_by``, ...) or mark candidates ``none``.

Feature layouts are versioned (``FEATURE_SPEC``) and shared by training export and inference so the
train-time and serve-time graph schemas cannot drift.
"""

from __future__ import annotations

import math

import numpy as np

from ..models import SCHEMA_VERSION

NODE_TYPES = ['line', 'curve', 'arc', 'polyline', 'rect', 'circle', 'text']
EDGE_TYPES = ['connects_to', 'intersects', 'parallel_near', 'near']
FEATURE_SPEC = {
    'version': 'ka-graph-features-1',
    'node': [f'type_{t}' for t in NODE_TYPES]
    + ['length', 'dir_sin2', 'dir_cos2', 'bbox_w', 'bbox_h', 'stroke_width', 'closed', 'degree', 'raster_inferred', 'n_points'],
    'edge': [f'type_{t}' for t in EDGE_TYPES] + ['distance', 'angle_sin', 'overlap', 'same_layer', 'perpendicular'],
}
NODE_DIM = len(FEATURE_SPEC['node'])
EDGE_DIM = len(FEATURE_SPEC['edge'])


def _dir(pts):
    a = np.asarray(pts, dtype=float)
    if len(a) < 2:
        return 0.0, 0.0, 0.0
    d = a[-1] - a[0]
    L = float(np.sum(np.linalg.norm(np.diff(a, axis=0), axis=1)))
    th = math.atan2(d[1], d[0])
    return L, math.sin(2 * th), math.cos(2 * th)


def build_graph(primitives: list[dict], image_size, params: dict | None = None) -> dict:
    from shapely import STRtree
    from shapely.geometry import LineString, Point, box

    p = {'connect_tol': 0.0025, 'parallel_tol': 0.018, 'parallel_angle_deg': 3.0, 'near_k': 3, 'near_tol': 0.03}
    p.update(params or {})
    W, H = image_size
    diag = math.hypot(W, H)
    nodes, geoms, dirs = [], [], []
    for pr in primitives:
        t = pr['type'] if pr['type'] in NODE_TYPES else 'polyline'
        pts = pr['pts_px']
        L, s2, c2 = _dir(pts) if t != 'text' else (0.0, 0.0, 0.0)
        x0, y0, x1, y1 = pr['bbox']
        feat = [0.0] * NODE_DIM
        feat[NODE_TYPES.index(t)] = 1.0
        feat[7] = 10 * L / diag
        feat[8], feat[9] = s2, c2
        feat[10], feat[11] = 10 * (x1 - x0) / diag, 10 * (y1 - y0) / diag
        feat[12] = min(float(pr.get('width') or 0.0), 4.0) / 2.0
        feat[13] = 1.0 if pr.get('closed') else 0.0
        feat[15] = 1.0 if pr.get('provenance') == 'raster_inferred' else 0.0
        feat[16] = min(len(pts), 64) / 64
        nodes.append({
            'id': pr['id'], 'type': t, 'label': None, 'primitive_ids': [pr['id']], 'object_uid': None,
            'bbox': pr['bbox'], 'features': feat, 'layer': pr.get('layer'), 'text': pr.get('text'),
            'provenance': pr.get('provenance', 'import'), 'review': 'pending', 'confidence': None,
        })
        if t == 'text':
            geoms.append(box(x0, y0, x1, y1))
        elif len(pts) >= 2:
            geoms.append(LineString(pts))
        else:
            geoms.append(Point(pts[0]))
        dirs.append(np.asarray(pts[-1], float) - np.asarray(pts[0], float) if len(pts) >= 2 else np.zeros(2))

    edges = {}

    def add(i, j, etype, dist, ang, overlap=0.0, perp=0.0):
        if i == j:
            return
        a, b = (i, j) if i < j else (j, i)
        k = (a, b, etype)
        if k in edges:
            return
        ef = [0.0] * EDGE_DIM
        ef[EDGE_TYPES.index(etype)] = 1.0
        ef[4] = min(10 * dist / diag, 5.0)
        ef[5] = ang
        ef[6] = overlap
        la, lb = nodes[a].get('layer'), nodes[b].get('layer')
        ef[7] = 1.0 if (la is not None and la == lb) else 0.0
        ef[8] = perp
        edges[k] = {
            'id': f'e{len(edges)}', 'source': nodes[a]['id'], 'target': nodes[b]['id'], 'type': etype, 'label': None,
            'directed': False, 'features': ef, 'provenance': 'geometric', 'review': 'pending', 'confidence': None,
        }

    if not geoms:
        return _wrap(nodes, [], p)
    tree = STRtree(geoms)
    ctol = p['connect_tol'] * diag
    ptol = p['parallel_tol'] * diag
    for i, g in enumerate(geoms):
        ti = nodes[i]['type']
        if ti == 'text':
            continue
        di = dirs[i]
        ni = np.linalg.norm(di)
        for j in tree.query(g.buffer(max(ctol, ptol))):
            j = int(j)
            if j <= i or nodes[j]['type'] == 'text':
                continue
            gj = geoms[j]
            dj = dirs[j]
            nj = np.linalg.norm(dj)
            sin_ang = abs(float(di[0] * dj[1] - di[1] * dj[0]) / (ni * nj)) if ni > 0 and nj > 0 else 0.0
            dist = g.distance(gj)
            # endpoint contact
            ends_i = [np.asarray(g.coords[0]), np.asarray(g.coords[-1])]
            ends_j = [np.asarray(gj.coords[0]), np.asarray(gj.coords[-1])]
            touch = min(np.linalg.norm(a - b) for a in ends_i for b in ends_j)
            if touch <= ctol:
                add(i, j, 'connects_to', touch, sin_ang, perp=1.0 if sin_ang > 0.98 else 0.0)
            elif dist <= 1e-6 and g.intersects(gj):
                add(i, j, 'intersects', 0.0, sin_ang, perp=1.0 if sin_ang > 0.98 else 0.0)
            elif dist <= ctol:
                add(i, j, 'connects_to', dist, sin_ang, perp=1.0 if sin_ang > 0.98 else 0.0)
            if ti == 'line' and nodes[j]['type'] == 'line' and sin_ang < math.sin(math.radians(p['parallel_angle_deg'])) and 1e-6 < dist <= ptol:
                u = di / ni
                pi = sorted([float(np.dot(np.asarray(c), u)) for c in g.coords])
                pj = sorted([float(np.dot(np.asarray(c), u)) for c in gj.coords])
                ov = max(0.0, min(pi[-1], pj[-1]) - max(pi[0], pj[0])) / max(min(pi[-1] - pi[0], pj[-1] - pj[0]), 1e-6)
                if ov > 0.5:
                    add(i, j, 'parallel_near', dist, sin_ang, overlap=min(ov, 1.0))
    # text -> nearest geometry ("near" candidates for label association)
    geo_idx = [i for i, n in enumerate(nodes) if n['type'] != 'text']
    if geo_idx:
        for i, n in enumerate(nodes):
            if n['type'] != 'text':
                continue
            c = geoms[i].centroid
            cand = [int(j) for j in tree.query(c.buffer(p['near_tol'] * diag)) if nodes[int(j)]['type'] != 'text']
            cand.sort(key=lambda j: geoms[j].distance(c))
            for j in cand[: p['near_k']]:
                add(i, j, 'near', geoms[j].distance(c), 0.0)
    elist = list(edges.values())
    deg = {}
    for e in elist:
        deg[e['source']] = deg.get(e['source'], 0) + 1
        deg[e['target']] = deg.get(e['target'], 0) + 1
    for n in nodes:
        n['features'][14] = min(deg.get(n['id'], 0), 20) / 10.0
    return _wrap(nodes, elist, p)


def _wrap(nodes, edges, params):
    return {
        'schema_version': SCHEMA_VERSION, 'feature_spec': FEATURE_SPEC['version'], 'builder_params': params,
        'nodes': nodes, 'edges': edges, 'graph_labels': {}, 'objects': {},
    }


def graph_stats(g: dict) -> dict:
    nodes, edges = g.get('nodes', []), g.get('edges', [])
    by_type = {}
    for e in edges:
        by_type[e['type']] = by_type.get(e['type'], 0) + 1
    return {
        'nodes': len(nodes), 'edges': len(edges), 'edge_types': by_type,
        'labeled_nodes': sum(1 for n in nodes if n.get('label')),
        'labeled_edges': sum(1 for e in edges if e.get('label')),
        'approved_nodes': sum(1 for n in nodes if n.get('review') == 'approved'),
        'objects': len({n['object_uid'] for n in nodes if n.get('object_uid')}),
    }


def validate_graph(g: dict, node_classes=None, edge_classes=None) -> list[dict]:
    """Topology + label validation. Returns issues [{severity, code, message, ids}]."""
    issues = []
    ids = [n['id'] for n in g.get('nodes', [])]
    idset = set(ids)
    if len(ids) != len(idset):
        issues.append({'severity': 'error', 'code': 'duplicate_node_id', 'message': 'Duplicate node ids', 'ids': []})
    seen = set()
    obj_of = {n['id']: n.get('object_uid') for n in g.get('nodes', [])}
    label_of = {n['id']: n.get('label') for n in g.get('nodes', [])}
    for e in g.get('edges', []):
        if e['source'] not in idset or e['target'] not in idset:
            issues.append({'severity': 'error', 'code': 'dangling_edge', 'message': f'Edge {e["id"]} references a missing node', 'ids': [e['id']]})
            continue
        if e['source'] == e['target']:
            issues.append({'severity': 'error', 'code': 'self_loop', 'message': f'Edge {e["id"]} is a self loop', 'ids': [e['id']]})
        k = (min(e['source'], e['target']), max(e['source'], e['target']), e.get('type'), e.get('label'))
        if k in seen:
            issues.append({'severity': 'warning', 'code': 'duplicate_edge', 'message': f'Duplicate edge {e["id"]}', 'ids': [e['id']]})
        seen.add(k)
        if edge_classes and e.get('label') and e['label'] not in edge_classes:
            issues.append({'severity': 'error', 'code': 'unknown_edge_label', 'message': f'Edge label {e["label"]} not in taxonomy', 'ids': [e['id']]})
        if e.get('label') == 'same_object':
            oa, ob = obj_of.get(e['source']), obj_of.get(e['target'])
            if oa and ob and oa != ob:
                issues.append({'severity': 'error', 'code': 'grouping_conflict',
                               'message': f'Edge {e["id"]} says same_object but nodes are grouped into different objects', 'ids': [e['id']]})
            la, lb = label_of.get(e['source']), label_of.get(e['target'])
            if la and lb and la != lb:
                issues.append({'severity': 'warning', 'code': 'same_object_label_mismatch',
                               'message': f'Edge {e["id"]}: same_object nodes have different labels ({la} vs {lb})', 'ids': [e['id']]})
    for n in g.get('nodes', []):
        if node_classes and n.get('label') and n['label'] not in node_classes:
            issues.append({'severity': 'error', 'code': 'unknown_node_label', 'message': f'Node label {n["label"]} not in taxonomy', 'ids': [n['id']]})
    # objects whose member nodes disagree on label
    members = {}
    for n in g.get('nodes', []):
        if n.get('object_uid'):
            members.setdefault(n['object_uid'], set()).add(n.get('label'))
    for oid, labs in members.items():
        labs.discard(None)
        if len(labs) > 1:
            issues.append({'severity': 'warning', 'code': 'object_mixed_labels', 'message': f'Object {oid} mixes labels {sorted(labs)}', 'ids': [oid]})
    deg = {i: 0 for i in idset}
    for e in g.get('edges', []):
        if e['source'] in deg:
            deg[e['source']] += 1
        if e['target'] in deg:
            deg[e['target']] += 1
    iso = [i for i, d in deg.items() if d == 0]
    if ids and len(iso) / len(ids) > 0.25:
        issues.append({'severity': 'warning', 'code': 'many_isolated_nodes', 'message': f'{len(iso)} of {len(ids)} nodes have no edges', 'ids': iso[:50]})
    unlabeled = [n['id'] for n in g.get('nodes', []) if not n.get('label')]
    if unlabeled:
        issues.append({'severity': 'info', 'code': 'unlabeled_nodes', 'message': f'{len(unlabeled)} nodes have no label', 'ids': unlabeled[:50]})
    return issues
