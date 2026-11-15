import os

import pytest
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def ka_paths(settings, tmp_path):
    settings.KA_STORAGE_ROOT = str(tmp_path / 'storage')
    settings.KA_RUNS_ROOT = str(tmp_path / 'runs')
    os.environ['KA_ALLOW_FAULT_INJECTION'] = '1'
    os.environ.setdefault('KA_TORCH_THREADS', '2')
    from kentucky.security import rate_limiter

    rate_limiter.reset()
    yield


@pytest.fixture
def org_a(db):
    from kentucky.samples.factories import make_org

    return make_org('alice@a.test', 'Org A')


@pytest.fixture
def org_b(db):
    from kentucky.samples.factories import make_org

    return make_org('bob@b.test', 'Org B')


def login(client, user):
    # real login view: Label Studio's session-timeout middleware requires the session stamps it sets
    r = client.post('/user/login/', {'email': user.email, 'password': 'ka-dev-password-1'})
    assert r.status_code == 302, r.status_code
    return client


@pytest.fixture
def client_a(org_a):
    return login(APIClient(), org_a[0])


@pytest.fixture
def client_b(org_b):
    return login(APIClient(), org_b[0])


@pytest.fixture
def labeled_dataset(org_a):
    """Vector PDFs (rotated too), DXF and scans with simulated human CV + graph labels, approved."""
    from kentucky.labeling import sync_from_label_studio
    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user, classes=['wall', 'door', 'window'])
    plans = {}
    for seed, fmt, rot in [(21, 'pdf', 0), (22, 'pdf', 90), (23, 'dxf', 0), (24, 'pdf', 0), (25, 'png', 0)]:
        plan, doc, sheet = F.upload_plan(ds, user, seed, fmt, rot)
        F.simulate_cv_annotation(sheet, plan, fmt, user)
        if fmt != 'png':
            F.simulate_graph_labeling(sheet, plan, fmt, user)
        plans[sheet.id] = (plan, fmt)
    sync_from_label_studio(ds)
    F.approve_all(ds, user)
    return ds, plans
