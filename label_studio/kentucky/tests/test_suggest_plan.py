"""Find more with AI picks, per item type, the model that measured best on it."""

import pytest


@pytest.mark.django_db
def test_each_item_type_comes_from_its_best_model(org_a):
    from kentucky import storage
    from kentucky.models import ModelVersion, RegisteredModel
    from kentucky.review_api import _suggest_plan
    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user)
    _, _, sheet = F.upload_plan(ds, user, 71, 'pdf')
    k = storage.key(org.id, 'models', 'p', 'm.pt')
    storage.put_bytes(k, b'x')
    det = RegisteredModel.objects.create(organization=org, name='det', task='instance_segmentation', catalog_id='det-rtdetrv2-r18')
    seg = RegisteredModel.objects.create(organization=org, name='seg', task='semantic_segmentation', catalog_id='seg-lraspp-mbv3')
    inst_metrics = {'test': {'n': 1, 'per_class_pr': {'door': {'tp': 8, 'fn': 0, 'recall': 1.0}, 'wall': {'tp': 9, 'fn': 30, 'recall': 0.23}},
                             'per_class_ap': {'door': 0.9, 'wall': 0.1}}}
    seg_metrics = {'test': {'per_class': {'__background__': {'gt_pixels': 9, 'iou': 0.9}, 'wall': {'gt_pixels': 9, 'iou': 0.4, 'recall': 0.9},
                                          'door': {'gt_pixels': 9, 'iou': 0.1, 'recall': 0.4}},
                            'objects': {'wall': {'gt_count': 39, 'missing_rate': 0.0}, 'door': {'gt_count': 8, 'missing_rate': 0.5}}}}
    a = ModelVersion.objects.create(organization=org, model=det, version=1, artifact_key=k, artifact_sha256='0' * 64, metrics=inst_metrics, status='ready')
    b = ModelVersion.objects.create(organization=org, model=seg, version=1, artifact_key=k, artifact_sha256='0' * 64, metrics=seg_metrics, status='ready')
    plan = {mv.id: set(labels) for mv, labels in _suggest_plan(sheet)}
    assert plan == {a.id: {'door'}, b.id: {'wall'}}
    b.status = 'archived'
    b.save()
    assert {mv.id: set(labels) for mv, labels in _suggest_plan(sheet)} == {a.id: {'door', 'wall'}}
