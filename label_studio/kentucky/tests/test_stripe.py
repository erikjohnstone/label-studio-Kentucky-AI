"""Stripe in test mode, with Stripe's HTTP API mocked (no network): customer is created once, the test card is
attached as default, every ledger charge becomes exactly one invoice item keyed by the ledger's idempotency key,
and live keys stay blocked unless an operator explicitly enables live mode."""

from decimal import Decimal
from urllib.parse import parse_qs

import pytest

responses = pytest.importorskip('responses')


@pytest.mark.django_db
def test_stripe_test_mode_customer_card_and_idempotent_invoice_items(settings, client_a, org_a):
    from kentucky.billing import ledger
    from kentucky.models import LedgerEntry

    settings.KA_STRIPE_SECRET_KEY = 'sk_test_dummy'
    user, org = org_a
    with responses.RequestsMock() as rs:
        rs.add(responses.POST, 'https://api.stripe.com/v1/customers', json={'id': 'cus_1'})
        rs.add(responses.POST, 'https://api.stripe.com/v1/payment_methods/pm_card_visa/attach', json={'id': 'pm_1'})
        rs.add(responses.POST, 'https://api.stripe.com/v1/customers/cus_1', json={'id': 'cus_1'})
        rs.add(responses.POST, 'https://api.stripe.com/v1/invoiceitems', json={'id': 'ii_1'})
        r = client_a.patch('/api/ka/billing/', {'payment_method': 'test_card'}, format='json')
        assert r.status_code == 200 and r.data['account']['stripe_customer'] and r.data['account']['payment_method_status'] == 'test_card'
        e, created = ledger.record(org, LedgerEntry.Kind.INFERENCE, 'inf:x:1', 1, 'request', '0.0004', '0.002', 'deployment', 1, 'one call')
        e2, created2 = ledger.record(org, LedgerEntry.Kind.INFERENCE, 'inf:x:1', 1, 'request', '0.0004', '0.002', 'deployment', 1, 'one call')
        assert created and not created2 and e.pk == e2.pk
        items = [c for c in rs.calls if c.request.url.endswith('/invoiceitems')]
        assert len(items) == 1
        assert items[0].request.headers['Idempotency-Key'] == 'inf:x:1'
        body = parse_qs(items[0].request.body)
        assert body['customer'] == ['cus_1'] and Decimal(body['unit_amount_decimal'][0]) == Decimal('0.2')
        e.refresh_from_db()
        assert e.stripe_status == 'submitted_test' and e.stripe_ref == 'ii_1'
        assert [c.request.headers.get('Idempotency-Key') for c in rs.calls if c.request.url.endswith('/customers')] == [f'ka-org-{org.id}-customer']


@pytest.mark.django_db
def test_live_key_blocked_without_operator_flag(settings, org_a):
    from kentucky.billing import ledger
    from kentucky.models import LedgerEntry

    settings.KA_STRIPE_SECRET_KEY = 'sk_live_dummy'
    settings.KA_STRIPE_LIVE = False
    assert ledger.stripe_mode() == 'blocked_live_key'
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rs:
        e, _ = ledger.record(org_a[1], LedgerEntry.Kind.INFERENCE, 'inf:y:1', 1, 'request', '0', '0.5')
        assert not rs.calls  # nothing sent to Stripe
    e.refresh_from_db()
    assert e.stripe_status == 'blocked_live_key'
