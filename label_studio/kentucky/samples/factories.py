"""Fixtures that drive the real platform code paths with synthetic plans (tests + demo seeding).

``simulate_cv_annotation`` writes genuine Label Studio Annotation rows (as an annotator would via the
editor), and ``simulate_graph_labeling`` saves a human graph version - the platform then syncs,
reviews, versions, exports and trains exactly as for real customer data.
"""

from __future__ import annotations

import io
import math

import numpy as np

from .. import coords
from . import synthetic as syn


def make_org(email, title):
    from organizations.models import Organization
    from users.models import User

    u = User.objects.filter(email=email).first() or User.objects.create_user(email=email, password='ka-dev-password-1')
    if u.active_organization is None:
        org = Organization.create_organization(created_by=u, title=title)
        u.active_organization = org
        u.save()
    return u, u.active_organization


def make_dataset(org, user, name='Synthetic office plans', classes=None):
    from ..labeling import default_taxonomy_classes, ensure_project
    from ..models import Dataset, Taxonomy

    ds = Dataset.objects.create(organization=org, name=name, created_by=user)
    Taxonomy.objects.create(organization=org, dataset=ds, version=1, classes=default_taxonomy_classes(classes))
    ensure_project(ds, user)
    return ds


def upload_plan(ds, user, seed, fmt='pdf', rotate=0, group=None, scanned_skew=0.0):
    from ..ingest.pipeline import create_document, process_document

    plan = syn.generate_plan(seed)
    if fmt == 'pdf':
        data, name = syn.to_pdf(plan, rotate), f'plan_{seed}.pdf'
    elif fmt == 'dxf':
        data, name = syn.to_dxf(plan), f'plan_{seed}.dxf'
    else:
        buf = io.BytesIO()
        syn.to_raster(plan, 2.0, scanned=True, seed=seed, skew_deg=scanned_skew).save(buf, 'PNG')
        data, name = buf.getvalue(), f'scan_{seed}.png'
    doc = create_document(ds, name, data, user, split_group=group or f'building_{seed}')
    sheets = process_document(doc)
    return plan, doc, sheets[0]


def plan_to_image_px(plan, sheet, fmt):
    """Mapping from synthetic plan coordinates (pt, y-down) into the sheet image."""
    M = np.asarray(sheet.source_to_image, dtype=float)
    if fmt == 'pdf':
        return lambda pts: coords.apply(M, pts)  # plan space == unrotated top-left PDF source space
    if fmt == 'dxf':
        H = plan.height
        return lambda pts: coords.apply(M, [(x, H - y) for x, y in pts])
    return lambda pts: np.asarray(pts, dtype=float) * 2.0  # raster rendered at 2 px/pt (skew ignored)


def simulate_cv_annotation(sheet, plan, fmt, user, classes=('wall', 'door', 'window'), drop_every=0):
    """Create a real LS annotation with polygon results for each GT object."""
    from tasks.models import Annotation

    to_px = plan_to_image_px(plan, sheet, fmt)
    W, H = sheet.width, sheet.height
    result = []
    for k, (oid, o) in enumerate(plan.objects.items()):
        if o['label'] not in classes or (drop_every and k % drop_every == 0):
            continue
        poly = to_px(o['polygon']).tolist()
        result.append({'id': f'r{oid}', 'from_name': 'polygonlabels', 'to_name': 'image', 'type': 'polygonlabels',
                       'original_width': W, 'original_height': H, 'image_rotation': 0,
                       'value': {'points': coords.image_to_ls_percent(poly, W, H), 'polygonlabels': [o['label']]}})
    return Annotation.objects.create(task_id=sheet.ls_task_id, project_id=sheet.ls_task.project_id, result=result, completed_by=user)


def match_primitives(sheet, plan, fmt):
    """Map extracted primitive ids -> GT (label, object id) by geometry."""
    from ..ingest.pipeline import load_primitives

    to_px = plan_to_image_px(plan, sheet, fmt)
    prims = load_primitives(sheet)['primitives']
    gt = []
    for p in plan.prims:
        pts = to_px(p.pts)
        gt.append((p, pts))
    out = {}
    tol = 0.004 * math.hypot(sheet.width, sheet.height)
    for pr in prims:
        a = np.asarray(pr['pts_px'], dtype=float)
        best, bd = None, 1e18
        for p, pts in gt:
            if pr['type'] == 'text':
                if p.kind != 'text':
                    continue
                x0, y0, x1, y1 = pr['bbox']
                ax, ay = pts[0]
                d = 0 if (x0 - tol <= ax <= x1 + tol and y0 - 2 * tol <= ay <= y1 + 2 * tol) else math.hypot((x0 + x1) / 2 - ax, (y0 + y1) / 2 - ay)
            else:
                if p.kind == 'text':
                    continue
                e1 = min(np.linalg.norm(a[0] - pts[0]) + np.linalg.norm(a[-1] - pts[-1]),
                         np.linalg.norm(a[0] - pts[-1]) + np.linalg.norm(a[-1] - pts[0]))
                d = e1
            if d < bd:
                bd, best = d, p
        if best is not None and bd < 6 * tol:
            out[pr['id']] = (best.label, best.obj)
    return out


def simulate_graph_labeling(sheet, plan, fmt, user, approve=True):
    from ..agent.labeling_assistant import current_graph, save_graph_version
    from ..models import Review

    g = current_graph(sheet)
    m = match_primitives(sheet, plan, fmt)
    data = {**g.graph, 'nodes': [dict(n) for n in g.graph['nodes']], 'edges': [dict(e) for e in g.graph['edges']]}
    lab = {}
    for n in data['nodes']:
        if n['id'] in m:
            n['label'], n['object_uid'] = m[n['id']]
        else:
            n['label'] = 'other'
        n['provenance'], n['review'] = 'human', 'approved'
        lab[n['id']] = (n['label'], n.get('object_uid'))
    for e in data['edges']:
        (la, oa), (lb, ob) = lab[e['source']], lab[e['target']]
        if oa and oa == ob:
            e['label'] = 'same_object'
        elif {la, lb} in ({'door', 'wall'}, {'window', 'wall'}) and e['type'] in ('connects_to', 'intersects'):
            e['label'] = 'hosted_by'
        else:
            e['label'] = 'none'
        e['provenance'], e['review'] = 'human', 'approved'
    sg = save_graph_version(sheet, data, user, source='human', message='simulated annotator')
    if approve:
        sg.review_status = Review.APPROVED
        sg.save(update_fields=['review_status'])
    return sg, len(m), len(data['nodes'])


def approve_all(dataset, user):
    from django.utils import timezone

    from ..models import CanonicalObject, Review

    return CanonicalObject.objects.filter(dataset=dataset, deleted=False).update(review_status=Review.APPROVED, reviewed_by=user,
                                                                                 reviewed_at=timezone.now())
