"""Immutable dataset versions with leakage-free splits."""

from __future__ import annotations

import hashlib
import json
import random

from django.db import transaction

from ..models import CanonicalObject, DatasetVersion, Review, SheetGraph
from .quality import readiness, tight_bbox


def group_split(sheets, ratios=(0.7, 0.15, 0.15), seed: int = 0, strategy: str = 'group'):
    """Assign whole groups (building/project -> document -> sheet) to splits.

    ``strategy``: ``group`` (SourceDocument.split_group), ``document`` or ``sheet``.
    Sheets are never tiled across splits: training-time crops are taken only within train sheets.
    """
    key = {
        'group': lambda s: s.document.split_group or f'doc{s.document_id}',
        'document': lambda s: f'doc{s.document_id}',
        'sheet': lambda s: f'sheet{s.id}',
    }[strategy]
    groups = {}
    for s in sheets:
        groups.setdefault(key(s), []).append(s.id)
    names = sorted(groups)
    rng = random.Random(seed)
    rng.shuffle(names)
    total = sum(len(v) for v in groups.values())
    out = {'train': [], 'val': [], 'test': []}
    gmap = {'train': [], 'val': [], 'test': []}
    targets = {'val': ratios[1] * total, 'test': ratios[2] * total}
    # ensure val/test get at least one group when there are >= 3 groups
    for split in ('test', 'val'):
        if len(names) >= 3 or (split == 'val' and len(names) >= 2):
            while names and (len(out[split]) < max(1, targets[split] - 0.5)):
                g = names.pop()
                out[split] += groups[g]
                gmap[split].append(g)
                if len(out[split]) >= targets[split]:
                    break
    for g in names:
        out['train'] += groups[g]
        gmap['train'].append(g)
    return {**{k: sorted(v) for k, v in out.items()}, 'groups': gmap, 'strategy': strategy, 'seed': seed, 'ratios': list(ratios)}


def assert_no_leakage(splits) -> None:
    s = [set(splits[k]) for k in ('train', 'val', 'test')]
    if s[0] & s[1] or s[0] & s[2] or s[1] & s[2]:
        raise AssertionError('sheet appears in more than one split')
    g = [set(splits['groups'][k]) for k in ('train', 'val', 'test')]
    if g[0] & g[1] or g[0] & g[2] or g[1] & g[2]:
        raise AssertionError('group appears in more than one split')


@transaction.atomic
def create_version(dataset, user=None, seed: int = 0, strategy: str = 'group', ratios=(0.7, 0.15, 0.15), notes='') -> DatasetVersion:
    from ..labeling import current_taxonomy

    tax = current_taxonomy(dataset)
    report = readiness(dataset, tax)
    sheets = list(dataset.sheets.select_related('document').order_by('id'))
    splits = group_split(sheets, ratios, seed, strategy)
    assert_no_leakage(splits)
    objs = CanonicalObject.objects.filter(dataset=dataset, deleted=False, review_status=Review.APPROVED).order_by('id')
    graphs = SheetGraph.objects.filter(sheet__dataset=dataset, is_current=True, review_status=Review.APPROVED)
    manifest = {
        'sheets': [{
            'id': s.id, 'document_id': s.document_id, 'name': s.name, 'width': s.width, 'height': s.height,
            'has_vector': s.has_vector, 'vector_provenance': s.vector_provenance, 'image_key': s.image_key,
            'source_to_image': s.source_to_image, 'split_group': s.document.split_group, 'document_kind': s.document.kind,
        } for s in sheets],
        'objects': [{
            'uid': o.uid, 'sheet_id': o.sheet_id, 'label': o.label, 'geometry_type': o.geometry_type,
            'geometry': o.geometry, 'bbox': tight_bbox(o), 'provenance': o.provenance, 'is_negative': o.is_negative,
            'primitive_ids': o.primitive_ids, 'proposal_id': o.proposal_id, 'annotator_id': o.annotator_id,
            'reviewed_by_id': o.reviewed_by_id,
        } for o in objs],
        'negative_sheets': sorted({o.sheet_id for o in CanonicalObject.objects.filter(dataset=dataset, is_negative=True, deleted=False).exclude(review_status=Review.REJECTED)}),
        'graphs': [{'sheet_id': g.sheet_id, 'graph_version_id': g.id, 'version': g.version} for g in graphs],
    }
    h = hashlib.sha256(json.dumps([tax.classes, manifest, splits], sort_keys=True, default=str).encode()).hexdigest()
    tax.frozen = True
    tax.save(update_fields=['frozen'])
    last = dataset.versions.order_by('-version').first()
    return DatasetVersion.objects.create(
        organization_id=dataset.organization_id, dataset=dataset, version=(last.version + 1 if last else 1),
        taxonomy={'version': tax.version, 'classes': tax.classes}, manifest=manifest, splits=splits,
        readiness=report, content_hash=h, created_by=user, notes=notes,
    )
