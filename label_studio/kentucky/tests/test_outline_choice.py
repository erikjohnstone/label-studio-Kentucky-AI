"""One-click outline training picks the architecture the benchmarks favour for the plan set."""

import pytest


@pytest.mark.django_db
def test_scans_with_enough_checked_sheets_get_dinov2(org_a):
    from kentucky import storage
    from kentucky.api import _outline_choice
    from kentucky.models import DatasetVersion, ModelVersion, RegisteredModel
    from kentucky.samples import factories as F

    user, org = org_a
    scans, vec = F.make_dataset(org, user, name='scans'), F.make_dataset(org, user, name='vectors')
    sheets = [F.upload_plan(scans, user, 80 + i, 'png')[2] for i in range(5)]
    F.upload_plan(vec, user, 90, 'pdf')
    for s in sheets[:4]:
        s.labeling_status = 'reviewed'
        s.save()
    assert _outline_choice(scans) == 'seg-lraspp-mbv3'  # only 4 checked: DINOv2 trailed on small sets
    sheets[4].labeling_status = 'reviewed'
    sheets[4].save()
    assert _outline_choice(scans) == 'seg-dinov2-s'
    assert _outline_choice(vec) == 'seg-lraspp-mbv3'  # tied on vectors at many times the time

    # an architecture already trained on the set is kept, so one-click continues from it
    k = storage.key(org.id, 'models', 'p', 'm.pt')
    storage.put_bytes(k, b'x')
    dv = DatasetVersion.objects.create(organization=org, dataset=vec, version=1, taxonomy={}, manifest={}, splits={}, content_hash='0' * 64, created_by=user)
    rm = RegisteredModel.objects.create(organization=org, name='seg', task='semantic_segmentation', catalog_id='seg-dinov2-s')
    ModelVersion.objects.create(organization=org, model=rm, version=1, artifact_key=k, artifact_sha256='0' * 64,
                                dataset_version=dv, status='ready')
    assert _outline_choice(vec) == 'seg-dinov2-s'

    # a newer, worse experiment does not take over the default; the best-scoring architecture does
    def seg_metrics(missing):
        return {'test': {'per_class': {'__background__': {'gt_pixels': 9, 'iou': 0.9}, 'wall': {'gt_pixels': 9, 'iou': 0.5}},
                         'objects': {'wall': {'gt_count': 20, 'missing_rate': missing}}}}
    ModelVersion.objects.filter(model=rm).update(metrics=seg_metrics(0.0))
    lr = RegisteredModel.objects.create(organization=org, name='seg2', task='semantic_segmentation', catalog_id='seg-lraspp-mbv3')
    ModelVersion.objects.create(organization=org, model=lr, version=1, artifact_key=k, artifact_sha256='0' * 64,
                                dataset_version=dv, status='ready', metrics=seg_metrics(0.5))
    assert _outline_choice(vec) == 'seg-dinov2-s'
    ModelVersion.objects.filter(model=lr).update(metrics=seg_metrics(0.0))
    ModelVersion.objects.filter(model=rm).update(metrics=seg_metrics(0.4))
    assert _outline_choice(vec) == 'seg-lraspp-mbv3'
