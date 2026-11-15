"""Test E - organizations cannot access one another's drawings, datasets, annotations, jobs, checkpoints, models, keys."""

import pytest
from django.core import signing
from django.test import Client

from kentucky import storage
from kentucky.models import ApiKey, Deployment, ModelVersion, Proposal, RegisteredModel, TrainingJob


@pytest.fixture
def org_a_assets(org_a):
    from kentucky.agent.labeling_assistant import current_graph
    from kentucky.datasets.versioning import create_version
    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user)
    plan, doc, sheet = F.upload_plan(ds, user, 31, 'pdf')
    F.simulate_cv_annotation(sheet, plan, 'pdf', user)
    current_graph(sheet)
    v = create_version(ds, user)
    job = TrainingJob.objects.create(organization=org, dataset_version=v, task='node_classification', catalog_id='gnn-sage-node', init='scratch', config={})
    k = storage.key(org.id, 'models', 'x', 'model.pt')
    storage.put_bytes(k, b'weights')
    rm = RegisteredModel.objects.create(organization=org, name='m', task='node_classification', catalog_id='gnn-sage-node')
    mv = ModelVersion.objects.create(organization=org, model=rm, version=1, artifact_key=k, artifact_sha256='0' * 64,
                                     license={'commercially_deployable': True})
    dep = Deployment.objects.create(organization=org, name='d', slug='dep-a', model=rm, active_version=mv)
    key, raw = ApiKey.generate(org, 'a-key', user)
    prop = Proposal.objects.create(organization=org, dataset=ds, sheet=sheet, kind='node_label', agent='x', agent_version='1', payload={'node_ids': [], 'label': 'wall'})
    return {'ds': ds, 'sheet': sheet, 'version': v, 'job': job, 'mv': mv, 'dep': dep, 'key': key, 'raw': raw, 'prop': prop, 'doc': doc}


@pytest.mark.django_db
def test_cross_org_api_access_denied(org_a_assets, client_a, client_b):
    a = org_a_assets
    gets = [f'datasets/{a["ds"].id}/', f'datasets/{a["ds"].id}/sheets/', f'datasets/{a["ds"].id}/documents/', f'datasets/{a["ds"].id}/objects/',
            f'datasets/{a["ds"].id}/readiness/', f'datasets/{a["ds"].id}/versions/', f'datasets/{a["ds"].id}/proposals/',
            f'sheets/{a["sheet"].id}/', f'sheets/{a["sheet"].id}/primitives/', f'sheets/{a["sheet"].id}/graph/', f'jobs/{a["job"].id}/',
            f'model-versions/{a["mv"].id}/', f'model-versions/{a["mv"].id}/download/']
    for path in gets:
        assert client_a.get('/api/ka/' + path).status_code == 200, path
        assert client_b.get('/api/ka/' + path).status_code == 404, path
    posts = [(f'datasets/{a["ds"].id}/objects/review/', {'ids': [1], 'status': 'approved'}), (f'versions/{a["version"].id}/export/', {}),
             (f'jobs/{a["job"].id}/cancel/', {}), (f'deployments/{a["dep"].id}/pause/', {}), (f'api-keys/{a["key"].id}/revoke/', {}),
             (f'proposals/{a["prop"].id}/review/', {'action': 'reject'}), (f'sheets/{a["sheet"].id}/graph/review/', {'status': 'approved'}),
             (f'model-versions/{a["mv"].id}/predict/', {'sheet_id': a['sheet'].id}), (f'datasets/{a["ds"].id}/agent/quality-review/', {}),
             ('jobs/', {'dataset_version_id': a['version'].id, 'catalog_id': 'gnn-sage-node'}), ('deployments/', {'model_version_id': a['mv'].id, 'confirm': True})]
    for path, body in posts:
        assert client_b.post('/api/ka/' + path, body, format='json').status_code == 404, path
    # lists are scoped
    for path in ('datasets/', 'jobs/', 'models/', 'deployments/', 'api-keys/', 'audit/'):
        assert client_b.get('/api/ka/' + path).json() == [], path
    assert client_b.delete(f'/api/ka/datasets/{a["ds"].id}/').status_code == 404
    a['key'].refresh_from_db()
    assert a['key'].revoked_at is None


@pytest.mark.django_db
def test_drawing_files_and_signed_urls_isolated(org_a_assets, org_a, org_b):
    a = org_a_assets
    from kentucky.tests.conftest import login

    ca, cb = login(Client(), org_a[0]), login(Client(), org_b[0])
    url = f'/ka/files/sheet/{a["sheet"].id}/image.png'
    assert ca.get(url).status_code == 200
    assert cb.get(url).status_code == 404
    assert Client().get(url).status_code in (302, 401, 403)
    good = storage.signed_url(a['doc'].storage_key, org_a[1].id)
    assert Client().get(good).status_code == 200  # signed URL works without session...
    forged = signing.dumps({'k': a['doc'].storage_key, 'o': org_b[1].id, 'f': ''}, salt=storage.SIGNING_SALT)
    assert Client().get(f'/ka/files/signed/{forged}').status_code == 404  # ...but only for the owning org's prefix
    tampered = good.replace('/signed/', '/signed/x')
    assert Client().get(tampered).status_code == 404
    with pytest.raises(storage.StorageError):
        storage.path(a['doc'].storage_key, org_b[1].id)
    with pytest.raises(storage.StorageError):
        storage.key(org_a[1].id, '..', 'org_2', 'x')


@pytest.mark.django_db
def test_api_keys_scoped_to_org(org_a_assets, org_b):
    a = org_a_assets
    _, raw_b = ApiKey.generate(org_b[1], 'b-key', org_b[0])
    c = Client()
    r = c.post('/api/ka/v1/deployments/dep-a/predict', {'sheet_id': a['sheet'].id}, content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {raw_b}')
    assert r.status_code == 404
    r = c.post('/api/ka/v1/deployments/dep-a/predict', {}, content_type='application/json', HTTP_AUTHORIZATION='Bearer ka_invalid')
    assert r.status_code in (401, 403)
    r = c.post('/api/ka/v1/deployments/dep-a/predict', {}, content_type='application/json')
    assert r.status_code == 401
    # a key never stores the raw secret
    assert not ApiKey.objects.filter(key_hash=raw_b).exists() and ApiKey.objects.filter(key_hash=ApiKey.hash(raw_b)).exists()
