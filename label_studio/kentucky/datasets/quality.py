"""Dataset quality gates and readiness reports.

A dataset is NOT ready merely because annotations exist: only human-approved objects / reviewed
graphs count as ground truth, and every task has explicit minimums (see ``MINIMUMS``).
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from ..graph.builder import validate_graph
from ..models import CanonicalObject, Review, SheetGraph

MINIMUMS = {
    'semantic_segmentation': {'sheets': 2, 'objects_per_class': 3},
    'instance_segmentation': {'sheets': 2, 'objects_per_class': 3},
    'node_classification': {'graphs': 2, 'nodes_per_class': 5},
    'edge_classification': {'graphs': 2, 'edges_per_class': 5},
}


def polygon_issues(poly, W, H):
    from shapely.geometry import Polygon

    out = []
    if not poly or len(poly) < 3:
        return ['too_few_vertices']
    p = Polygon(poly)
    if not p.is_valid:
        out.append('self_intersecting')
    if p.area < 4.0:
        out.append('degenerate_area')
    a = np.asarray(poly)
    if (a[:, 0] < -1).any() or (a[:, 1] < -1).any() or (a[:, 0] > W + 1).any() or (a[:, 1] > H + 1).any():
        out.append('out_of_bounds')
    return out


def tight_bbox(obj: CanonicalObject):
    g = obj.geometry or {}
    if g.get('polygon'):
        a = np.asarray(g['polygon'], dtype=float)
        return [float(a[:, 0].min()), float(a[:, 1].min()), float(np.ptp(a[:, 0])), float(np.ptp(a[:, 1]))]
    return g.get('bbox')


def _iou(a, b):
    from shapely.geometry import Polygon

    pa, pb = Polygon(a), Polygon(b)
    if not pa.is_valid or not pb.is_valid:
        pa, pb = pa.buffer(0), pb.buffer(0)
    inter = pa.intersection(pb).area
    union = pa.union(pb).area
    return inter / union if union > 0 else 0.0


def readiness(dataset, taxonomy) -> dict:
    sheets = list(dataset.sheets.all())
    cv_classes = taxonomy.names('cv')
    node_classes = taxonomy.names('node')
    edge_classes = taxonomy.names('edge')
    objs = list(CanonicalObject.objects.filter(dataset=dataset, deleted=False))
    approved = [o for o in objs if o.review_status == Review.APPROVED and not o.is_negative]
    pending = [o for o in objs if o.review_status == Review.PENDING and not o.is_negative]
    rejected = [o for o in objs if o.review_status == Review.REJECTED]
    negatives = {o.sheet_id for o in objs if o.is_negative and o.review_status != Review.REJECTED}
    blockers, warnings, infos = [], [], []

    # --- per-object geometry validity
    by_sheet = defaultdict(list)
    sheet_map = {s.id: s for s in sheets}
    invalid = []
    for o in approved:
        by_sheet[o.sheet_id].append(o)
        if o.geometry_type in ('polygon', 'bbox'):
            iss = polygon_issues(o.geometry.get('polygon'), sheet_map[o.sheet_id].width, sheet_map[o.sheet_id].height)
            if iss:
                invalid.append({'object': o.uid, 'issues': iss})
    if invalid:
        blockers.append({'code': 'invalid_geometry', 'message': f'{len(invalid)} approved objects have invalid geometry', 'items': invalid[:50]})

    # --- duplicates / overlaps
    dups, overlaps = [], []
    for sid, lst in by_sheet.items():
        polys = [(o, o.geometry.get('polygon')) for o in lst if o.geometry.get('polygon') and len(o.geometry['polygon']) >= 3]
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                oi, pi = polys[i]
                oj, pj = polys[j]
                bi, bj = tight_bbox(oi), tight_bbox(oj)
                if bi[0] > bj[0] + bj[2] or bj[0] > bi[0] + bi[2] or bi[1] > bj[1] + bj[3] or bj[1] > bi[1] + bi[3]:
                    continue
                iou = _iou(pi, pj)
                if iou > 0.95 and oi.label == oj.label:
                    dups.append([oi.uid, oj.uid])
                elif iou > 0.5 and oi.label != oj.label:
                    overlaps.append({'objects': [oi.uid, oj.uid], 'labels': [oi.label, oj.label], 'iou': round(iou, 3)})
    if dups:
        warnings.append({'code': 'duplicate_objects', 'message': f'{len(dups)} near-duplicate object pairs', 'items': dups[:50]})
    if overlaps:
        warnings.append({'code': 'conflicting_overlap', 'message': f'{len(overlaps)} overlapping objects with different labels', 'items': overlaps[:50]})

    # --- annotator disagreement (multiple LS annotations per task)
    disagreements = []
    by_task_ann = defaultdict(lambda: defaultdict(Counter))
    for o in objs:
        if o.ls_annotation_id:
            by_task_ann[o.sheet_id][o.ls_annotation_id][o.label] += 1
    for sid, anns in by_task_ann.items():
        if len(anns) > 1:
            counts = list(anns.values())
            labels = set().union(*[set(c) for c in counts])
            diff = {lab: [c.get(lab, 0) for c in counts] for lab in labels if len({c.get(lab, 0) for c in counts}) > 1}
            if diff:
                disagreements.append({'sheet': sid, 'per_label_counts': diff})
    if disagreements:
        warnings.append({'code': 'annotator_disagreement', 'message': f'{len(disagreements)} sheets where annotators disagree on object counts', 'items': disagreements})

    # --- missing labels
    labeled_sheets = {o.sheet_id for o in approved} | negatives
    missing = [s.id for s in sheets if s.id not in labeled_sheets]
    if missing:
        warnings.append({'code': 'unlabeled_sheets', 'message': f'{len(missing)} sheets have no approved labels and are not marked negative', 'items': missing})
    if pending:
        warnings.append({'code': 'pending_review', 'message': f'{len(pending)} objects await review and are excluded from ground truth', 'items': []})

    cls_counts = Counter(o.label for o in approved)
    empty = [c for c in cv_classes if c != 'unknown' and cls_counts.get(c, 0) == 0]
    if empty and approved:
        infos.append({'code': 'classes_without_examples', 'message': f'Classes with no approved examples (excluded from training): {empty}', 'items': empty})
    active = {c: n for c, n in cls_counts.items() if c != 'unknown'}
    if active and max(active.values()) / max(min(active.values()), 1) > 20:
        warnings.append({'code': 'class_imbalance', 'message': 'Class imbalance ratio exceeds 20:1', 'items': [active]})

    # --- graphs
    graphs = {g.sheet_id: g for g in SheetGraph.objects.filter(sheet__dataset=dataset, is_current=True)}
    approved_graphs = {sid: g for sid, g in graphs.items() if g.review_status == Review.APPROVED}
    node_counts, edge_counts = Counter(), Counter()
    graph_issues = {}
    for sid, g in approved_graphs.items():
        iss = [i for i in validate_graph(g.graph, node_classes, edge_classes) if i['severity'] == 'error']
        if iss:
            graph_issues[sid] = iss
        for n in g.graph['nodes']:
            if n.get('label') and is_verified(n):
                node_counts[n['label']] += 1
        for e in g.graph['edges']:
            if e.get('label') and is_verified(e):
                edge_counts[e['label']] += 1
        labeled_nodes = {n['id'] for n in g.graph['nodes'] if n.get('label') and n['label'] != 'other'}
        touched = {x for e in g.graph['edges'] if e.get('label') and e['label'] != 'none' for x in (e['source'], e['target'])}
        if labeled_nodes and not (labeled_nodes & touched) and any(e.get('label') for e in g.graph['edges']):
            warnings.append({'code': 'missing_relationships', 'message': f'Sheet {sid}: labeled nodes have no labeled relationships', 'items': [sid]})
    if graph_issues:
        blockers.append({'code': 'graph_topology_errors', 'message': f'{len(graph_issues)} approved graphs have topology errors', 'items': graph_issues})
    pending_graphs = [sid for sid, g in graphs.items() if g.review_status != Review.APPROVED]
    if pending_graphs:
        warnings.append({'code': 'graphs_pending_review', 'message': f'{len(pending_graphs)} graphs are not approved and are excluded', 'items': pending_graphs})

    ready = {}
    m = MINIMUMS
    cv_ok_classes = [c for c, n in active.items() if n >= m['semantic_segmentation']['objects_per_class']]
    cv_sheets = len({o.sheet_id for o in approved})
    ready['semantic_segmentation'] = cv_sheets >= m['semantic_segmentation']['sheets'] and bool(cv_ok_classes) and not invalid
    ready['instance_segmentation'] = ready['semantic_segmentation']
    nk = [c for c, n in node_counts.items() if n >= m['node_classification']['nodes_per_class']]
    ready['node_classification'] = len(approved_graphs) >= m['node_classification']['graphs'] and len(nk) >= 2 and not graph_issues
    ek = [c for c, n in edge_counts.items() if n >= m['edge_classification']['edges_per_class']]
    ready['edge_classification'] = len(approved_graphs) >= m['edge_classification']['graphs'] and len(ek) >= 2 and not graph_issues
    for task, ok in ready.items():
        if not ok:
            infos.append({'code': f'not_ready_{task}', 'message': f'Not ready for {task}: minimums {m[task]}', 'items': []})
    return {
        'ready_for': ready,
        'blockers': blockers,
        'warnings': warnings,
        'info': infos,
        'stats': {
            'sheets': len(sheets), 'objects_total': len(objs), 'approved': len(approved), 'pending': len(pending),
            'rejected': len(rejected), 'negative_sheets': len(negatives), 'class_counts': dict(cls_counts),
            'graphs': len(graphs), 'approved_graphs': len(approved_graphs), 'node_label_counts': dict(node_counts),
            'edge_label_counts': dict(edge_counts),
            'vector_sheets': sum(1 for s in sheets if s.has_vector), 'raster_sheets': sum(1 for s in sheets if not s.has_vector),
        },
    }


def is_verified(item: dict) -> bool:
    """Graph element counts as ground truth only if a human set it or approved it."""
    if item.get('review') == 'rejected':
        return False
    return item.get('review') == 'approved' or item.get('provenance') == 'human'
