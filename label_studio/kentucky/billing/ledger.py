"""Idempotent usage ledger + Stripe (test-mode) integration point.

Every billable event has a deterministic ``idempotency_key`` (e.g. ``job:42:compute``). The unique
constraint on ``LedgerEntry.idempotency_key`` guarantees we never record (or charge) the same event
twice, even under retries or concurrent workers. The same key is sent to Stripe as the
``Idempotency-Key`` header, so Stripe also de-duplicates.

No Stripe call is made unless ``KA_STRIPE_SECRET_KEY`` is configured AND it is a test key
(``sk_test_``) or ``KA_STRIPE_LIVE=1`` is set explicitly.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import BillingAccount, LedgerEntry

logger = logging.getLogger(__name__)


def account(org) -> BillingAccount:
    acct, _ = BillingAccount.objects.get_or_create(organization=org)
    return acct


def record(org, kind, key, quantity, unit, infra, charge, ref_type='', ref_id='', description='') -> tuple[LedgerEntry, bool]:
    existing = LedgerEntry.objects.filter(idempotency_key=key).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            e = LedgerEntry.objects.create(
                organization=org, kind=kind, idempotency_key=key, quantity=Decimal(str(quantity)), unit=unit,
                infra_cost_usd=Decimal(str(infra)), customer_charge_usd=Decimal(str(charge)), reference_type=ref_type,
                reference_id=str(ref_id), description=description[:500],
            )
    except IntegrityError:
        return LedgerEntry.objects.get(idempotency_key=key), False
    submit_to_stripe(e)
    return e, True


def month_to_date(org) -> Decimal:
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    v = LedgerEntry.objects.filter(organization=org, created_at__gte=start).exclude(kind=LedgerEntry.Kind.CREDIT).aggregate(
        s=Sum('customer_charge_usd'))['s']
    return v or Decimal('0')


def committed_training(org) -> Decimal:
    """Authorized-but-unbilled maximum of active jobs (reserved against the cap)."""
    from ..models import TERMINAL_STATES, TrainingJob

    v = TrainingJob.objects.filter(organization=org).exclude(status__in=TERMINAL_STATES).exclude(authorized_at=None).aggregate(
        s=Sum('max_cost_usd'))['s']
    return v or Decimal('0')


def check_spend(org, amount: Decimal) -> tuple[bool, str]:
    acct = account(org)
    used = month_to_date(org) + committed_training(org)
    if used + Decimal(amount) > acct.monthly_spend_cap_usd:
        return False, f'Spend cap ${acct.monthly_spend_cap_usd} would be exceeded (month-to-date + reserved ${used}, requested ${amount})'
    return True, 'ok'


def usage_summary(org, days=30) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = LedgerEntry.objects.filter(organization=org, created_at__gte=since)
    by_kind = {}
    for e in qs:
        k = by_kind.setdefault(e.kind, {'quantity': Decimal('0'), 'charge': Decimal('0'), 'infra': Decimal('0'), 'count': 0})
        k['quantity'] += e.quantity
        k['charge'] += e.customer_charge_usd
        k['infra'] += e.infra_cost_usd
        k['count'] += 1
    return {
        'days': days,
        'by_kind': {k: {kk: (str(vv) if isinstance(vv, Decimal) else vv) for kk, vv in v.items()} for k, v in by_kind.items()},
        'total_charge': str(sum((v['charge'] for v in by_kind.values()), Decimal('0'))),
        'total_infra': str(sum((v['infra'] for v in by_kind.values()), Decimal('0'))),
        'month_to_date': str(month_to_date(org)),
        'cap': str(account(org).monthly_spend_cap_usd),
        'reserved_for_active_jobs': str(committed_training(org)),
    }


def stripe_mode() -> str:
    key = getattr(settings, 'KA_STRIPE_SECRET_KEY', '') or ''
    if not key:
        return 'not_configured'
    if key.startswith('sk_test_'):
        return 'test'
    return 'live' if getattr(settings, 'KA_STRIPE_LIVE', False) else 'blocked_live_key'


def _stripe(method, path, idem=None, **data):
    import requests

    r = requests.request(method, 'https://api.stripe.com/v1' + path, auth=(settings.KA_STRIPE_SECRET_KEY, ''),
                         headers={'Idempotency-Key': idem} if idem else {}, data=data, timeout=15)
    r.raise_for_status()
    return r.json()


def ensure_stripe_customer(org, test_card=False) -> str | None:
    """Create the org's Stripe customer once (idempotent per org). In test mode, optionally attach Stripe's
    ``pm_card_visa`` test card as the default so invoices can be finalized end to end. Never in live mode."""
    mode = stripe_mode()
    if mode not in ('test', 'live'):
        return None
    acct = account(org)
    if not acct.stripe_customer_id:
        c = _stripe('POST', '/customers', idem=f'ka-org-{org.id}-customer', name=org.title[:200], **{'metadata[ka_org]': str(org.id)})
        acct.stripe_customer_id = c['id']
        acct.save(update_fields=['stripe_customer_id'])
    if test_card and mode == 'test':
        pm = _stripe('POST', '/payment_methods/pm_card_visa/attach', idem=f'ka-org-{org.id}-pm-visa', customer=acct.stripe_customer_id)
        _stripe('POST', f'/customers/{acct.stripe_customer_id}', **{'invoice_settings[default_payment_method]': pm['id']})
    return acct.stripe_customer_id


def submit_to_stripe(entry: LedgerEntry):
    """Report a charge to Stripe as an invoice item (test mode by default)."""
    mode = stripe_mode()
    if mode in ('not_configured', 'blocked_live_key') or entry.customer_charge_usd <= 0:
        LedgerEntry.objects.filter(pk=entry.pk).update(stripe_status=mode if entry.customer_charge_usd > 0 else 'zero_amount')
        return
    acct = account(entry.organization)
    if not acct.stripe_customer_id:
        LedgerEntry.objects.filter(pk=entry.pk).update(stripe_status='no_customer')
        return
    try:
        # Stripe amounts are integer cents; sub-cent usage (single API calls) accrues as decimal amounts
        r = _stripe('POST', '/invoiceitems', idem=entry.idempotency_key, customer=acct.stripe_customer_id, currency='usd',
                    unit_amount_decimal=str((entry.customer_charge_usd * 100).quantize(Decimal('0.000001'))), quantity=1,
                    description=entry.description or entry.kind, **{'metadata[ledger_key]': entry.idempotency_key})
        LedgerEntry.objects.filter(pk=entry.pk).update(stripe_status=f'submitted_{mode}', stripe_ref=r.get('id', ''))
    except Exception as e:  # noqa: BLE001
        logger.warning('stripe submit failed: %s', e)
        LedgerEntry.objects.filter(pk=entry.pk).update(stripe_status='error')
