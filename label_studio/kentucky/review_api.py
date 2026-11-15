"""Review-first labeling API (the contractor "Check the AI's work" screen).

The Label Studio annotation stays the source of truth for a sheet's labels: the screen edits a list of
LS ``polygonlabels`` regions and saves it through ``sheet_markup``. AI suggestions are ``Proposal`` rows
(with provenance); this module lists them, records Keep / Dismiss decisions, runs "find more" and closes
out a sheet ("Done" = every label on it is checked and approved for training).
"""

from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import catalog, coords
from .agent import labeling_assistant as LA
from .api import _get
from .labeling import current_taxonomy, ensure_project, ensure_tasks
from .models import CanonicalObject, ModelVersion, Proposal, Review, Sheet
from .security import audit

TA_NICE = {'wall': 'walls', 'door': 'doors', 'window': 'windows', 'room': 'rooms'}


def _poly_px(r, W, H):
    v = r.get('value', {})
    if r.get('type') == 'polygonlabels':
        return coords.ls_percent_to_image(v.get('points', []), r.get('original_width') or W, r.get('original_height') or H)
    if r.get('type') == 'rectanglelabels':
        x, y, w, h = (v['x'] * W / 100, v['y'] * H / 100, v['width'] * W / 100, v['height'] * H / 100)
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return None


def _bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    iw, ih = max(0, min(ax1, bx1) - max(ax0, bx0)), max(0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    u = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / u if u > 0 else 0.0


def _annotation(sheet, user):
    from tasks.models import Annotation

    return Annotation.objects.filter(task_id=sheet.ls_task_id, completed_by=user, was_cancelled=False).order_by('-id').first()


def _sheet_state(s: Sheet, pending: int):
    if pending:
        return 'review'
    if s.labeling_status == 'reviewed':
        return 'done'
    q = CanonicalObject.objects.filter(sheet=s, deleted=False, is_negative=False)
    n = q.count()
    if n and not q.exclude(review_status=Review.APPROVED).exists():
        return 'done'  # every label on it has been checked
    return 'labeled' if n else 'empty'


def _dedupe(sheet, user):
    """Dismiss pending suggestions that duplicate a label already on the sheet (same type, IoU >= 0.5)."""
    ann = _annotation(sheet, user)
    have = []
    for r in (ann.result if ann else []) or []:
        p = _poly_px(r, sheet.width, sheet.height)
        lab = ((r.get('value') or {}).get(r.get('type')) or [None])[0]
        if p and len(p) >= 3:
            have.append((lab, _bbox(p)))
    n = 0
    for p in Proposal.objects.filter(sheet=sheet, kind=Proposal.Kind.CV_OBJECT, status='pending'):
        bb = _bbox(p.payload['polygon'])
        if any(lab == p.payload['label'] and _iou(bb, hb) >= 0.5 for lab, hb in have):
            p.status, p.reviewed_at = Proposal.Status.DISMISSED, timezone.now()
            p.explanation = (p.explanation + ' [auto-dismissed: duplicates an existing label]').strip()
            p.save(update_fields=['status', 'reviewed_at', 'explanation'])
            n += 1
    return n


def _suggest_plan(sheet):
    """Pick, for each item type, the org's model that measured best on it (its own held-out test), so e.g. doors
    come from a detector and walls from an outline model. Returns [(model version, [labels])], best first."""
    from .agent import training_advisor as TA

    qs = ModelVersion.objects.filter(organization=sheet.organization, status='ready',
                                     model__task__in=['instance_segmentation', 'semantic_segmentation']).select_related('model', 'dataset_version')
    best = {}
    for mv in qs:
        rc = TA.report_card(mv.metrics, mv.model.task)
        for it in (rc or {}).get('items', []):
            same = mv.dataset_version_id is not None and mv.dataset_version.dataset_id == sheet.dataset_id
            key = (round(it['score'], 2), same, mv.created_at)
            if it['score'] > 0 and (it['key'] not in best or key > best[it['key']][0]):
                best[it['key']] = (key, mv)
    plan = {}
    for label, (_, mv) in best.items():
        plan.setdefault(mv.id, (mv, []))[1].append(label)
    return sorted(plan.values(), key=lambda x: -len(x[1]))


@api_view(['GET'])
def sheet_review(request, pk):
    """Everything the review screen needs: the image, the user's labels (LS regions), pending AI suggestions, the plan set's sheets."""
    s = _get(Sheet, request, pk=pk)
    ensure_project(s.dataset)
    if not s.ls_task_id:
        ensure_tasks(s.dataset, [s])
        s.refresh_from_db()
    tax = current_taxonomy(s.dataset)
    ann = _annotation(s, request.user)
    pend = Proposal.objects.filter(sheet=s, kind=Proposal.Kind.CV_OBJECT, status='pending').order_by('-confidence', 'id')
    decided = Proposal.objects.filter(sheet=s, kind=Proposal.Kind.CV_OBJECT).exclude(status='pending').values('status').annotate(n=Count('id'))
    dec = {r['status']: r['n'] for r in decided}
    sheets = list(s.dataset.sheets.order_by('id'))
    pend_by = dict(Proposal.objects.filter(dataset=s.dataset, kind=Proposal.Kind.CV_OBJECT, status='pending')
                   .values_list('sheet_id').annotate(n=Count('id')).values_list('sheet_id', 'n'))
    i = [x.id for x in sheets].index(s.id)
    has_model = bool(_suggest_plan(s))
    return Response({
        'sheet': {'id': s.id, 'name': s.name, 'width': s.width, 'height': s.height, 'image_url': f'/ka/files/sheet/{s.id}/image.png',
                  'has_vector': s.has_vector, 'labeling_status': s.labeling_status},
        'dataset': {'id': s.dataset_id, 'name': s.dataset.name},
        'position': [i + 1, len(sheets)],
        'sheets': [{'id': x.id, 'name': x.name, 'image_url': f'/ka/files/sheet/{x.id}/image.png', 'state': _sheet_state(x, pend_by.get(x.id, 0)),
                    'pending': pend_by.get(x.id, 0)} for x in sheets],
        'classes': [c for c in tax.classes if c['kind'] == 'cv' and c['name'] != 'unknown'],
        'annotation': {'id': ann.id, 'result': ann.result} if ann else None,
        'suggestions': [{'id': p.id, 'label': p.payload['label'], 'polygon': p.payload['polygon'], 'confidence': p.confidence,
                         'source': 'model' if p.model_version_id else 'similar' if p.agent == LA.SIMILAR_AGENT else 'drawing',
                         'explanation': p.explanation} for p in pend],
        'decided': {'kept': dec.get('accepted', 0) + dec.get('modified', 0), 'dismissed': dec.get('rejected', 0) + dec.get('dismissed', 0)},
        'can_find_more': bool(s.has_vector or has_model),
        'user': {'id': request.user.id, 'email': request.user.email},
    })


@api_view(['POST'])
def sheet_decide(request, pk):
    """Record a Keep / Dismiss on one AI suggestion. The kept region itself is saved by the client into the LS annotation
    with id ``ka<proposal id>`` so provenance survives the sync (see labeling.sync_from_label_studio)."""
    s = _get(Sheet, request, pk=pk)
    p = Proposal.objects.filter(sheet=s, id=request.data.get('proposal_id'), kind=Proposal.Kind.CV_OBJECT).first()
    if p is None:
        raise ValidationError({'proposal_id': 'unknown suggestion'})
    action = request.data.get('action')
    if action not in ('keep', 'dismiss', 'undo'):
        raise ValidationError({'action': 'keep | dismiss | undo'})
    if action == 'undo':
        p.status, p.final_payload, p.reviewed_by, p.reviewed_at = Proposal.Status.PENDING, None, None, None
    elif action == 'dismiss':
        p.status, p.reviewed_by, p.reviewed_at = Proposal.Status.REJECTED, request.user, timezone.now()
    else:
        label = request.data.get('label') or p.payload['label']
        changed = label != p.payload['label']
        p.status = Proposal.Status.MODIFIED if changed else Proposal.Status.ACCEPTED
        p.final_payload = {**p.payload, 'label': label}
        p.reviewed_by, p.reviewed_at = request.user, timezone.now()
    p.save()
    audit(request, f'review.{action}', p, sheet=s.id)
    return Response({'id': p.id, 'status': p.status})


@api_view(['POST'])
def sheet_find_more(request, pk):
    """Ask the AI for suggestions on this sheet: the plan set's best trained model if there is one, otherwise the drawing's own geometry."""
    s = _get(Sheet, request, pk=pk)
    plan = _suggest_plan(s)
    source = 'model' if plan else 'drawing'
    props, used = [], []
    try:
        if plan:
            for mv, labels in plan:
                props += LA.propose_from_model(s, s.dataset, mv, labels=set(labels))
                arch = (catalog.get(mv.model.catalog_id) or {}).get('name', mv.model.catalog_id).replace(' (pretrained)', '')
                used.append(f'{" & ".join(TA_NICE.get(x, x) for x in sorted(labels))} by {arch} v{mv.version}')
        elif s.has_vector:
            props = LA.propose_cv_from_graph(s, s.dataset)
    except Exception as e:  # inference problems are reported, never hidden
        raise ValidationError({'detail': f'Could not read this sheet: {e}'})
    dup = _dedupe(s, request.user)
    audit(request, 'review.find_more', s, created=len(props), duplicates=dup, source=source, models=[mv.id for mv, _ in plan])
    return Response({'created': len(props) - dup, 'duplicates': dup, 'source': source,
                     'model': ('your models — ' + '; '.join(used)) if used else None})


@api_view(['POST'])
def sheet_find_similar(request, pk):
    """'Find more like this': search the sheet for repeats of the item the user marked."""
    s = _get(Sheet, request, pk=pk)
    poly, label = request.data.get('polygon'), request.data.get('label')
    if not isinstance(poly, list) or len(poly) < 3 or not label:
        raise ValidationError({'detail': 'polygon (3+ points) and label are required'})
    try:
        props = LA.find_similar(s, s.dataset, poly, label)
    except ValueError as e:
        raise ValidationError({'detail': str(e)})
    dup = _dedupe(s, request.user)
    audit(request, 'review.find_similar', s, created=len(props), duplicates=dup, label=label)
    return Response({'created': len(props) - dup, 'duplicates': dup, 'label': label})


@api_view(['POST'])
def sheet_done(request, pk):
    """The contractor has checked this sheet: approve every label on it for training and point to the next sheet that needs work."""
    s = _get(Sheet, request, pk=pk)
    left = Proposal.objects.filter(sheet=s, kind=Proposal.Kind.CV_OBJECT, status='pending').count()
    if left and not request.data.get('dismiss_rest'):
        return Response({'done': False, 'pending': left})
    if left:
        Proposal.objects.filter(sheet=s, kind=Proposal.Kind.CV_OBJECT, status='pending').update(
            status=Proposal.Status.DISMISSED, reviewed_by=request.user, reviewed_at=timezone.now())
    now = timezone.now()
    n = 0
    for o in CanonicalObject.objects.filter(sheet=s, deleted=False).exclude(review_status=Review.APPROVED):
        o.history.append({'at': now.isoformat(), 'by': request.user.id, 'action': 'review:approved', 'before': o.review_status, 'comment': 'sheet done'})
        o.review_status, o.reviewed_by, o.reviewed_at = Review.APPROVED, request.user, now
        o.save()
        n += 1
    s.labeling_status = 'reviewed'
    s.save(update_fields=['labeling_status'])
    audit(request, 'review.sheet_done', s, approved=n)
    sheets = list(s.dataset.sheets.order_by('id'))
    i = [x.id for x in sheets].index(s.id)
    nxt = next((x.id for x in sheets[i + 1:] + sheets[:i] if x.labeling_status != 'reviewed'), None)
    done = sum(1 for x in sheets if x.labeling_status == 'reviewed' or x.id == s.id)
    return Response({'done': True, 'approved': n, 'next': nxt, 'sheets_done': done, 'sheets_total': len(sheets)})


# ------------------------------------------------------------------------------------------------ home overview
def _drawing(s: Sheet, limit=400):
    objs = CanonicalObject.objects.filter(sheet=s, deleted=False, is_negative=False).values('label', 'geometry')[:limit]
    return {'id': s.id, 'name': s.name, 'width': s.width, 'height': s.height, 'image_url': f'/ka/files/sheet/{s.id}/image.png',
            'items': [{'label': o['label'], 'polygon': o['geometry']['polygon']} for o in objs if (o['geometry'] or {}).get('polygon')]}


@api_view(['GET'])
def home(request):
    """One call for the Plan sets screen: every plan set with per-sheet state and a cover drawing, plus the single next step."""
    from .api import _ser_job, org_of
    from .agent import training_advisor as TA
    from .models import Dataset, Deployment, TrainingJob
    from .orchestration import service as orch

    org = org_of(request)
    out, nxt = [], None
    active = TrainingJob.objects.filter(organization=org, status__in=list(orch.ACTIVE) + ['QUEUED', 'VALIDATING']).order_by('-id').first()
    for d in Dataset.objects.filter(organization=org, archived=False).order_by('-id'):
        sheets = list(d.sheets.order_by('id'))
        pend_by = dict(Proposal.objects.filter(dataset=d, kind=Proposal.Kind.CV_OBJECT, status='pending')
                       .values_list('sheet_id').annotate(n=Count('id')).values_list('sheet_id', 'n'))
        st = [{'id': s.id, 'state': _sheet_state(s, pend_by.get(s.id, 0)), 'pending': pend_by.get(s.id, 0)} for s in sheets]
        counts = {r['label']: r['n'] for r in CanonicalObject.objects.filter(dataset=d, deleted=False, is_negative=False)
                  .values('label').annotate(n=Count('id'))}
        cover = next((s for s in sheets if CanonicalObject.objects.filter(sheet=s, deleted=False).exists()), sheets[0] if sheets else None)
        mv = (ModelVersion.objects.filter(organization=org, dataset_version__dataset=d, status='ready',
                                          model__task__in=['semantic_segmentation', 'instance_segmentation']).order_by('-created_at').first())
        rc = TA.report_card(mv.metrics, mv.model.task) if mv else None
        live = Deployment.objects.filter(organization=org, active_version__dataset_version__dataset=d, status='active').first()
        row = {'id': d.id, 'name': d.name, 'created_at': d.created_at, 'sheets': st, 'counts': counts,
               'objects': sum(counts.values()), 'pending': sum(pend_by.values()), 'scanned': sum(1 for s in sheets if not s.has_vector),
               'done': sum(1 for x in st if x['state'] == 'done'), 'cover': _drawing(cover) if cover else None,
               'model': {'id': mv.id, 'version': mv.version, 'score': rc['score'] if rc else None, 'ready': bool(rc and rc['ready_to_use']),
                         'job': mv.training_job_id} if mv else None,
               'live': {'id': live.id, 'name': live.name} if live else None,
               'training': _ser_job(active) if active and active.dataset_version.dataset_id == d.id else None}
        out.append(row)
    # the one next step (first match wins)
    for d in out:
        if d['training']:
            nxt = {'kind': 'training', 'dataset': d['id'], 'job': d['training']['id']}
            break
    if not nxt:
        d = max(out, key=lambda x: x['pending'], default=None)
        if d and d['pending']:
            s = max(d['sheets'], key=lambda x: x['pending'])
            nxt = {'kind': 'review', 'dataset': d['id'], 'sheet': s['id'], 'pending': d['pending'],
                   'sheet_pos': [i + 1 for i, x in enumerate(d['sheets']) if x['id'] == s['id']][0]}
    if not nxt:
        d = next((x for x in out if x['sheets'] and x['done'] < len(x['sheets']) and not x['model']), None)
        if d:
            s = next(x for x in d['sheets'] if x['state'] != 'done')
            nxt = {'kind': 'label' if s['state'] == 'empty' else 'check', 'dataset': d['id'], 'sheet': s['id']}
    if not nxt:
        d = next((x for x in out if x['done'] >= 2 and not x['model']), None) or next((x for x in out if x['model'] and not x['model']['ready']), None)
        if d:
            nxt = {'kind': 'train', 'dataset': d['id']}
    if not nxt:
        d = next((x for x in out if x['model'] and x['model']['ready'] and not x['live']), None)
        if d:
            nxt = {'kind': 'deploy', 'dataset': d['id'], 'model_version': d['model']['id']}
    if not nxt and out:
        nxt = {'kind': 'live' if any(x['live'] for x in out) else 'upload', 'dataset': out[0]['id']}
    return Response({'plan_sets': out, 'next': nxt or {'kind': 'upload'}})
