"""Always-on (dedicated) deployment hosting: the model is kept loaded and the deployment is billed per hour
while it is active. Idempotent per deployment-hour; partial hours are billed pro-rata when it is paused or
deleted; an org that would pass its monthly limit has its dedicated deployments paused (never silently overrun)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from ..models import AuditLog, Deployment, LedgerEntry
from . import ledger, pricing

HOUR = timedelta(hours=1)


def rates():
    p = pricing.pricing()
    return Decimal(p['dedicated_hosting_per_hour']), Decimal(p.get('dedicated_hosting_infra_per_hour', '0'))


def _bill(d: Deployment, start, end):
    charge_h, infra_h = rates()
    frac = Decimal(str(round((end - start).total_seconds() / 3600, 6)))
    if frac <= 0:
        return None
    e, _ = ledger.record(d.organization, LedgerEntry.Kind.HOSTING, f'hosting:{d.id}:{start.isoformat()}', frac, 'hour',
                         (infra_h * frac).quantize(Decimal('0.0001')), (charge_h * frac).quantize(Decimal('0.0001')),
                         'deployment', d.id, f'Always-on hosting · {d.name}')
    return e


def accrue(d: Deployment, now=None, final=False) -> int:
    """Bill full hours since the last accrual (and the partial hour when ``final``). Returns entries written."""
    if d.kind != 'dedicated':
        return 0
    now = now or timezone.now()
    start = d.hosting_billed_until or d.created_at
    n = 0
    charge_h, _ = rates()
    while start + HOUR <= now:
        ok, why = ledger.check_spend(d.organization, charge_h)
        if not ok:
            d.status = 'paused'
            d.history = d.history + [{'at': now.isoformat(), 'action': 'paused-spend-limit', 'version': d.active_version.version,
                                      'version_id': d.active_version_id, 'reason': why}]
            AuditLog.objects.create(organization=d.organization, action='deployment.paused_spend_limit', target_type='deployment',
                                    target_id=str(d.id), data={'reason': why})
            final = False
            break
        _bill(d, start, start + HOUR)
        start += HOUR
        n += 1
    if final and start < now:
        _bill(d, start, now)
        start = now
        n += 1
    d.hosting_billed_until = start
    d.save(update_fields=['hosting_billed_until', 'status', 'history'])
    return n


def accrue_all(now=None) -> int:
    n = 0
    for d in Deployment.objects.filter(kind='dedicated', status='active').select_related('organization', 'active_version'):
        n += accrue(d, now)
    return n
