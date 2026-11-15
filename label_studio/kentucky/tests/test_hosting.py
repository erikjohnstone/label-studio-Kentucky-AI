"""Always-on (dedicated) hosting: hourly metering, idempotent, pro-rata on pause, refused / auto-paused at the spend limit."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone


@pytest.fixture
def dedicated(org_a):
    from kentucky import storage
    from kentucky.models import Deployment, ModelVersion, RegisteredModel

    user, org = org_a
    k = storage.key(org.id, 'models', 'h', 'model.pt')
    storage.put_bytes(k, b'weights')
    rm = RegisteredModel.objects.create(organization=org, name='m', task='semantic_segmentation', catalog_id='seg-lraspp-mbv3')
    mv = ModelVersion.objects.create(organization=org, model=rm, version=1, artifact_key=k, artifact_sha256='0' * 64, license={'commercially_deployable': True})
    start = timezone.now() - timedelta(hours=2, minutes=30)
    d = Deployment.objects.create(organization=org, name='always', slug='always-1', model=rm, active_version=mv, kind='dedicated', hosting_billed_until=start)
    return d, mv, start


@pytest.mark.django_db
def test_hourly_hosting_is_idempotent_and_prorated(client_a, dedicated):
    from kentucky.billing import hosting
    from kentucky.models import LedgerEntry

    d, _, start = dedicated
    assert hosting.accrue_all() == 2
    assert hosting.accrue_all() == 0  # same hours never billed twice
    d.refresh_from_db()
    assert d.hosting_billed_until == start + timedelta(hours=2)
    r = client_a.post(f'/api/ka/deployments/{d.id}/pause/', {}, format='json')
    assert r.status_code == 200 and r.data['status'] == 'paused'
    rows = LedgerEntry.objects.filter(kind='hosting', reference_id=str(d.id)).order_by('id')
    hours = sum(e.quantity for e in rows)
    assert len(rows) == 3 and abs(hours - Decimal('2.5')) < Decimal('0.01')
    assert abs(sum(e.customer_charge_usd for e in rows) - Decimal('3.00')) < Decimal('0.02')
    assert all(e.infra_cost_usd < e.customer_charge_usd for e in rows)
    assert hosting.accrue_all() == 0  # paused: nothing accrues
    client_a.post(f'/api/ka/deployments/{d.id}/resume/', {}, format='json')
    d.refresh_from_db()
    assert hosting.accrue(d) == 0  # resume restarts the clock, no back-billing for paused time


@pytest.mark.django_db
def test_spend_limit_pauses_and_refuses_dedicated(client_a, dedicated, org_a):
    from kentucky.billing import hosting, ledger

    d, mv, _ = dedicated
    acct = ledger.account(org_a[1])
    acct.monthly_spend_cap_usd = Decimal('1.50')
    acct.save()
    hosting.accrue_all()
    d.refresh_from_db()
    assert d.status == 'paused' and d.history[-1]['action'] == 'paused-spend-limit'
    r = client_a.post('/api/ka/deployments/', {'model_version_id': mv.id, 'confirm': True, 'kind': 'dedicated'}, format='json')
    assert r.status_code == 400 and 'limit' in str(r.data)
    assert client_a.post('/api/ka/deployments/', {'model_version_id': mv.id, 'confirm': True, 'kind': 'bogus'}, format='json').status_code == 400
