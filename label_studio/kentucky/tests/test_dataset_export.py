"""Quality gates, versioning, leakage-free splits and export round-trips."""

import json

import numpy as np
import pytest
from PIL import Image

from kentucky.datasets.export import export_version, rle_decode, rle_encode
from kentucky.datasets.versioning import assert_no_leakage, create_version, group_split
from kentucky.models import CanonicalObject, Review


def test_rle_roundtrip():
    rng = np.random.default_rng(0)
    m = rng.random((37, 53)) > 0.7
    assert (rle_decode(rle_encode(m)) == m).all()


@pytest.mark.django_db
def test_version_export_roundtrip(labeled_dataset, tmp_path):
    ds, _ = labeled_dataset
    v = create_version(ds)
    assert_no_leakage(v.splits)
    assert all(v.readiness['ready_for'].values())
    out = export_version(v, tmp_path / 'b')
    approved = {o.uid: o for o in CanonicalObject.objects.filter(dataset=ds, review_status=Review.APPROVED)}
    coco_anns = []
    for split in ('train', 'val', 'test'):
        c = json.loads((out / 'coco' / f'{split}.json').read_text())
        img_ids = {i['id'] for i in c['images']}
        assert img_ids == set(v.splits[split])
        for a in c['annotations']:
            assert a['image_id'] in img_ids
            coco_anns.append(a)
    assert len(coco_anns) == len(approved)
    for a in coco_anns:  # polygon + tight bbox round-trip
        o = approved[a['ka_uid']]
        poly = np.array(a['segmentation'][0]).reshape(-1, 2)
        assert np.allclose(poly, np.array(o.geometry['polygon']), atol=1e-3)
        x0, y0 = poly.min(0)
        x1, y1 = poly.max(0)
        assert np.allclose(a['bbox'], [x0, y0, x1 - x0, y1 - y0], atol=1e-2)
    classes = json.loads((out / 'semantic' / 'classes.json').read_text())
    assert set(classes.values()) == {'__background__', 'wall', 'door', 'window'}
    sid = v.splits['train'][0]
    sem = np.asarray(Image.open(out / 'semantic' / f'{sid}.png'))
    assert set(np.unique(sem)) <= set(int(k) for k in classes) and (sem > 0).sum() > 1000
    import torch

    meta = json.loads((out / 'pyg' / 'meta.json').read_text())
    for split in ('train', 'val', 'test'):
        for d in torch.load(out / 'pyg' / f'{split}.pt', weights_only=False):
            assert d.x.shape[1] == meta['node_dim'] and d.edge_attr.shape[1] == meta['edge_dim']
            assert d.edge_index.max() < d.x.shape[0] and d.edge_index.shape[1] == d.edge_y.shape[0]
            assert (d.y >= 0).sum() > 0 and d.sheet_id in v.splits[split]


@pytest.mark.django_db
def test_unreviewed_and_rejected_never_ground_truth(labeled_dataset, tmp_path):
    ds, _ = labeled_dataset
    objs = list(CanonicalObject.objects.filter(dataset=ds)[:6])
    CanonicalObject.objects.filter(pk__in=[o.pk for o in objs[:3]]).update(review_status=Review.REJECTED)
    CanonicalObject.objects.filter(pk__in=[o.pk for o in objs[3:]]).update(review_status=Review.PENDING)
    v = create_version(ds)
    uids = {o['uid'] for o in v.manifest['objects']}
    assert not uids & {o.uid for o in objs}
    assert any(w['code'] == 'pending_review' for w in v.readiness['warnings'])


def test_group_split_never_leaks():
    class D:  # minimal sheet stand-ins
        def __init__(self, i, g):
            self.id, self.document_id = i, i // 2
            self.document = type('doc', (), {'split_group': g})()

    sheets = [D(i, f'b{i % 5}') for i in range(40)]
    for seed in range(5):
        s = group_split(sheets, seed=seed)
        assert_no_leakage(s)
        assert s['train'] and s['val'] and s['test']
        groups_of = {sid: sh.document.split_group for sh in sheets for sid in [sh.id]}
        for a in ('train', 'val', 'test'):
            for b in ('train', 'val', 'test'):
                if a < b:
                    assert not {groups_of[i] for i in s[a]} & {groups_of[i] for i in s[b]}


@pytest.mark.django_db
def test_quality_gates_flag_invalid_and_duplicates(labeled_dataset):
    from kentucky.datasets.quality import readiness
    from kentucky.labeling import current_taxonomy

    ds, _ = labeled_dataset
    o = CanonicalObject.objects.filter(dataset=ds, label='door').first()
    bow = [[0, 0], [100, 100], [100, 0], [0, 100]]  # self-intersecting
    CanonicalObject.objects.create(organization=ds.organization, dataset=ds, sheet=o.sheet, label='wall', geometry={'polygon': bow},
                                   review_status=Review.APPROVED)
    CanonicalObject.objects.create(organization=ds.organization, dataset=ds, sheet=o.sheet, label='door', geometry=dict(o.geometry),
                                   review_status=Review.APPROVED)
    r = readiness(ds, current_taxonomy(ds))
    assert any(b['code'] == 'invalid_geometry' for b in r['blockers'])
    assert any(w['code'] == 'duplicate_objects' for w in r['warnings'])
    assert r['ready_for']['semantic_segmentation'] is False
