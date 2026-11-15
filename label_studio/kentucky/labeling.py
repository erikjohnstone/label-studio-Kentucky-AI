"""Bridge between Kentucky datasets and Label Studio's annotation engine.

* Each Dataset owns one LS Project whose labeling config is generated from the dataset taxonomy.
* Each Sheet is one LS Task whose ``image`` URL is served by the org-checked sheet image view.
* LS annotations (polygon / rectangle / brush / keypoint results) are synced into
  ``CanonicalObject`` rows so CV and graph annotations share one identity + review workflow.
* Agent/model proposals are pushed into LS as Predictions (model_version ``<agent>@<version>``),
  so annotators accept/edit/reject them in the familiar LS editor. An annotation created from a
  prediction keeps ``parent_prediction``; the original proposal remains in ``Proposal.payload``.
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

import numpy as np
from django.db import transaction
from django.utils import timezone

from . import coords
from .models import CanonicalObject, Proposal, Provenance, Review, Sheet, Taxonomy

DEFAULT_CLASSES = [
    # name, kind, color, trade, aliases
    ('wall', 'cv', '#62d4dc', 'architectural', ['partition', 'wl']),
    ('door', 'cv', '#f0b24a', 'architectural', ['dr', 'opening']),
    ('window', 'cv', '#8fa8ff', 'architectural', ['glazing', 'wdw']),
    ('room', 'cv', '#4f9f6b', 'architectural', ['space']),
    ('floor_finish', 'cv', '#c3a6ff', 'finishes', ['flooring']),
    ('ceiling', 'cv', '#b3c0c6', 'finishes', []),
    ('roof', 'cv', '#7f8d94', 'architectural', []),
    ('duct', 'cv', '#3b40d2', 'mechanical', ['ductwork']),
    ('diffuser', 'cv', '#f05cc8', 'mechanical', ['grille', 'register']),
    ('hvac_equipment', 'cv', '#ff7b63', 'mechanical', ['ahu', 'rtu', 'vav']),
    ('electrical_device', 'cv', '#f2b45a', 'electrical', ['receptacle', 'switch']),
    ('plumbing_fixture', 'cv', '#97e6eb', 'plumbing', ['wc', 'lavatory', 'sink']),
    ('structural_member', 'cv', '#a7b4b9', 'structural', ['column', 'beam']),
    ('unknown', 'cv', '#848e8b', 'any', []),
    # graph node classes (primitive-level semantic roles)
    ('wall', 'node', '#62d4dc', 'architectural', []),
    ('door', 'node', '#f0b24a', 'architectural', []),
    ('window', 'node', '#8fa8ff', 'architectural', []),
    ('room_tag', 'node', '#4f9f6b', 'architectural', ['room_label']),
    ('other', 'node', '#848e8b', 'any', []),
    # graph edge (relation) classes
    ('same_object', 'edge', '#62d4dc', 'any', []),
    ('connects_to', 'edge', '#4f9f6b', 'any', []),
    ('hosted_by', 'edge', '#f0b24a', 'any', []),
    ('bounded_by', 'edge', '#8fa8ff', 'any', []),
    ('contained_in', 'edge', '#c3a6ff', 'any', []),
    ('labels', 'edge', '#f2b45a', 'any', []),
    ('none', 'edge', '#848e8b', 'any', []),
]


def default_taxonomy_classes(selected=None):
    out = []
    for name, kind, color, trade, aliases in DEFAULT_CLASSES:
        if selected and kind == 'cv' and name not in selected and name != 'unknown':
            continue
        out.append({'name': name, 'kind': kind, 'color': color, 'trade': trade, 'aliases': aliases})
    return out


def current_taxonomy(dataset) -> Taxonomy:
    return dataset.taxonomies.order_by('-version').first()


def label_config_for(tax: Taxonomy) -> str:
    cv = [c for c in tax.classes if c.get('kind') == 'cv']

    def labels(tag):
        inner = '\n'.join(f'    <Label value={quoteattr(c["name"])} background={quoteattr(c.get("color", "#62d4dc"))}/>' for c in cv)
        return f'  <{tag} name="{tag.lower()}" toName="image">\n{inner}\n  </{tag}>'

    return (
        '<View>\n'
        '  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="false" crosshair="true"/>\n'
        f'{labels("PolygonLabels")}\n{labels("RectangleLabels")}\n{labels("BrushLabels")}\n{labels("KeyPointLabels")}\n'
        '  <Choices name="sheet_flags" toName="image" choice="multiple" showInline="true">\n'
        '    <Choice value="negative_example"/>\n    <Choice value="needs_review"/>\n    <Choice value="out_of_scope"/>\n'
        '  </Choices>\n'
        '</View>'
    )


def label_config_markup(tax: Taxonomy) -> str:
    """Contractor labeling config for the embedded engine: outline (polygon) + box only, same control names as the
    full config so annotations stay compatible with sync and export."""
    cv = [c for c in tax.classes if c.get('kind') == 'cv' and c['name'] != 'unknown']

    def labels(tag):
        inner = '\n'.join(f'    <Label value={quoteattr(c["name"])} background={quoteattr(c.get("color", "#62d4dc"))}/>' for c in cv)
        return f'  <{tag} name="{tag.lower()}" toName="image" strokeWidth="2" opacity="0.35">\n{inner}\n  </{tag}>'

    return ('<View>\n  <Image name="image" value="$image" zoom="true" zoomControl="false" rotateControl="false" crosshair="true"/>\n'
            f'{labels("PolygonLabels")}\n{labels("RectangleLabels")}\n</View>')


def ensure_project(dataset, user=None):
    from projects.models import Project

    tax = current_taxonomy(dataset)
    cfg = label_config_for(tax)
    if dataset.project_id:
        p = dataset.project
        if p.label_config != cfg:
            p.label_config = cfg
            p.save()
        return p
    p = Project.objects.create(
        title=f'[KA] {dataset.name}'[:50], organization_id=dataset.organization_id, created_by=user or dataset.created_by,
        label_config=cfg, description=f'Kentucky AI dataset {dataset.id}',
    )
    dataset.project = p
    dataset.save(update_fields=['project'])
    return p


def sheet_image_url(sheet: Sheet) -> str:
    return f'/ka/files/sheet/{sheet.id}/image.png'


def ensure_tasks(dataset, sheets):
    from tasks.models import Task

    project = ensure_project(dataset)
    for s in sheets:
        if s.ls_task_id:
            continue
        t = Task.objects.create(project=project, data={'image': sheet_image_url(s), 'ka_sheet_id': s.id, 'sheet_name': s.name})
        s.ls_task = t
        s.save(update_fields=['ls_task'])


# ------------------------------------------------------------------------------- LS -> canonical
def _result_geometry(r, W, H):
    v = r.get('value', {})
    t = r.get('type')
    labels = v.get(t) or v.get('labels') or []
    label = labels[0] if labels else None
    ow, oh = r.get('original_width') or W, r.get('original_height') or H
    if t == 'polygonlabels':
        poly = coords.ls_percent_to_image(v.get('points', []), ow, oh)
        a = np.asarray(poly) if poly else np.zeros((0, 2))
        bbox = [float(a[:, 0].min()), float(a[:, 1].min()), float(np.ptp(a[:, 0])), float(np.ptp(a[:, 1]))] if len(a) else None
        return label, 'polygon', {'polygon': poly, 'bbox': bbox}
    if t == 'rectanglelabels':
        x, y = v['x'] * ow / 100, v['y'] * oh / 100
        w, h = v['width'] * ow / 100, v['height'] * oh / 100
        rot = float(v.get('rotation', 0) or 0)
        poly = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        if rot:
            c, s = np.cos(np.radians(rot)), np.sin(np.radians(rot))
            poly = [[x + (px - x) * c - (py - y) * s, y + (px - x) * s + (py - y) * c] for px, py in poly]
        return label, 'bbox', {'bbox': [x, y, w, h], 'polygon': poly, 'rotation': rot}
    if t == 'brushlabels':
        from label_studio_sdk.converter.brush import decode_rle

        flat = decode_rle(v['rle'])
        mask = np.reshape(flat, (oh, ow, 4))[:, :, 3] > 0
        ys, xs = np.nonzero(mask)
        bbox = [float(xs.min()), float(ys.min()), float(np.ptp(xs) + 1), float(np.ptp(ys) + 1)] if len(xs) else None
        return label, 'mask', {'mask_rle_ls': v['rle'], 'bbox': bbox, 'size': [oh, ow]}
    if t == 'keypointlabels':
        x, y = v['x'] * ow / 100, v['y'] * oh / 100
        return label, 'point', {'point': [x, y], 'bbox': [x, y, 0, 0]}
    return None, None, None


@transaction.atomic
def sync_from_label_studio(dataset, sheets=None) -> dict:
    """Upsert CanonicalObjects from current LS annotations. Idempotent."""
    from tasks.models import Annotation

    tax = current_taxonomy(dataset)
    sheets = sheets or list(dataset.sheets.exclude(ls_task=None))
    stats = {'created': 0, 'updated': 0, 'deleted': 0, 'negative': 0, 'unknown_label': 0}
    for sheet in sheets:
        seen = set()
        anns = Annotation.objects.filter(task_id=sheet.ls_task_id, was_cancelled=False).select_related('parent_prediction')
        for ann in anns:
            pred_ids = {}
            if ann.parent_prediction_id:
                for pr in ann.parent_prediction.result or []:
                    pred_ids[pr.get('id')] = pr
            for r in ann.result or []:
                if r.get('type') == 'choices' and 'negative_example' in r.get('value', {}).get('choices', []):
                    obj, created = CanonicalObject.objects.get_or_create(
                        organization_id=dataset.organization_id, dataset=dataset, sheet=sheet, ls_annotation_id=ann.id,
                        ls_result_id='__negative__', defaults={'label': '__background__', 'geometry_type': 'none', 'is_negative': True,
                                                              'annotator_id': ann.completed_by_id, 'provenance': Provenance.HUMAN},
                    )
                    seen.add(obj.pk)
                    stats['negative'] += 1
                    continue
                label, gtype, geom = _result_geometry(r, sheet.width, sheet.height)
                if gtype is None:
                    continue
                canon = tax.resolve(label, 'cv') if label else None
                if canon is None:
                    stats['unknown_label'] += 1
                    canon = 'unknown'
                prov = Provenance.HUMAN
                proposal = None
                if r.get('id') in pred_ids:
                    prov = Provenance.AGENT_ACCEPTED
                    proposal = Proposal.objects.filter(ls_prediction_id=ann.parent_prediction_id).first()
                obj = CanonicalObject.objects.filter(ls_annotation_id=ann.id, ls_result_id=r.get('id', ''), sheet=sheet).first()
                if obj is None:
                    obj = CanonicalObject.objects.create(
                        organization_id=dataset.organization_id, dataset=dataset, sheet=sheet, label=canon, geometry_type=gtype,
                        geometry=geom, provenance=prov, proposal=proposal, annotator_id=ann.completed_by_id,
                        ls_annotation_id=ann.id, ls_result_id=r.get('id', ''),
                        attributes={'ls_label': label},
                    )
                    stats['created'] += 1
                elif obj.geometry != geom or obj.label != canon or obj.deleted:
                    obj.history.append({'at': timezone.now().isoformat(), 'action': 'edited_in_label_studio',
                                        'before': {'label': obj.label, 'geometry': obj.geometry}})
                    obj.label, obj.geometry, obj.geometry_type, obj.deleted = canon, geom, gtype, False
                    obj.review_status = Review.PENDING  # edited after review -> must be re-reviewed
                    obj.save()
                    stats['updated'] += 1
                seen.add(obj.pk)
        gone = CanonicalObject.objects.filter(sheet=sheet, deleted=False).exclude(ls_annotation_id=None).exclude(pk__in=seen)
        stats['deleted'] += gone.update(deleted=True)
        n = CanonicalObject.objects.filter(sheet=sheet, deleted=False).count()
        if n and sheet.labeling_status == 'unlabeled':
            sheet.labeling_status = 'labeled'
            sheet.save(update_fields=['labeling_status'])
    return stats


# ------------------------------------------------------------------------------- proposals -> LS
def push_proposal_to_label_studio(proposal: Proposal):
    """Send a cv_object proposal into the LS editor as a prediction (not an annotation)."""
    from tasks.models import Prediction

    sheet = proposal.sheet
    if proposal.kind != Proposal.Kind.CV_OBJECT or not sheet or not sheet.ls_task_id:
        return None
    g = proposal.payload
    W, H = sheet.width, sheet.height
    poly = g.get('polygon')
    result = [{
        'id': f'ka{proposal.id}', 'from_name': 'polygonlabels', 'to_name': 'image', 'type': 'polygonlabels',
        'original_width': W, 'original_height': H, 'image_rotation': 0,
        'value': {'points': coords.image_to_ls_percent(poly, W, H), 'polygonlabels': [g['label']]},
    }]
    pred = Prediction.objects.create(
        task_id=sheet.ls_task_id, project_id=sheet.ls_task.project_id, result=result, score=proposal.confidence,
        model_version=f'{proposal.agent}@{proposal.agent_version}',
    )
    proposal.ls_prediction_id = pred.id
    proposal.save(update_fields=['ls_prediction_id'])
    return pred
