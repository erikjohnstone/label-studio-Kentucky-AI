"""New base models: DINOv2-S segmentation and RT-DETRv2 detection train through the normal job pipeline, register,
and serve predictions; their catalog records carry Apache-2.0 licenses with pinned revisions. Scratch init keeps
the test offline; pretrained weights are exercised by the measured runs in TEST_RESULTS.md."""

import pytest

from kentucky import catalog
from kentucky.datasets.versioning import create_version
from kentucky.inference.predictors import predict
from kentucky.models import JobStatus, ModelVersion
from kentucky.orchestration import service as S

from .test_training_failures import _wait


def test_catalog_license_records():
    for cid, hf in (('seg-dinov2-s', 'facebook/dinov2-with-registers-small'), ('det-rtdetrv2-r18', 'PekingU/rtdetr_v2_r18vd'),
                    ('det-dfine-s', 'ustc-community/dfine-small-coco'), ('det-rfdetr-s', 'Roboflow/rf-detr-small')):
        item = catalog.get(cid)
        pre = next(i for i in item['inits'] if i['id'] == 'pretrained')
        assert pre['hf_id'] == hf and pre['commercially_deployable'] is True and 'Apache-2.0' in pre['checkpoint_license']
        assert len(pre['revision']) == 40  # pinned to an exact commit


@pytest.mark.django_db
@pytest.mark.parametrize('cid,cfg', [
    ('seg-dinov2-s', {'epochs': 2, 'crop_size': 196, 'crops_per_sheet': 2, 'training_scale': 0.3}),
    ('det-rtdetrv2-r18', {'epochs': 2, 'crop_size': 320, 'crops_per_sheet': 2, 'batch_size': 2, 'training_scale': 0.3}),
    ('det-rfdetr-s', {'epochs': 1, 'crop_size': 320, 'crops_per_sheet': 1, 'batch_size': 2, 'training_scale': 0.3}),
])
def test_new_base_models_train_register_and_predict(org_a, labeled_dataset, cid, cfg):
    user, org = org_a
    ds, _ = labeled_dataset
    v = create_version(ds, user)
    j = S.create_job(org, user, v, cid, 'scratch', cfg)
    assert j.status == JobStatus.CREATED, j.error
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES, timeout=600)
    assert j.status == JobStatus.COMPLETED, j.error
    assert (j.final_metrics or {}).get('headline')
    mv = ModelVersion.objects.get(training_job=j)
    sheet = ds.sheets.order_by('id').first()
    r = predict(mv, {'sheet_id': sheet.id, 'score_threshold': 0.0}, org.id)
    assert r['image_size'][0] > 0 and isinstance(r['predictions'], list)
    for p in r['predictions'][:5]:
        assert p['label'] in ('wall', 'door', 'window') and len(p['polygon']) >= 3
