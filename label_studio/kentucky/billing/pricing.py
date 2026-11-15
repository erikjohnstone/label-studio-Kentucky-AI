"""Pricing, cost estimates and spend caps.

IMPORTANT: the default rates below are PLACEHOLDERS for development, not quotes from any provider.
Set real infrastructure rates (from your Modal / Lambda contract) and customer prices with
``KA_PRICING`` in settings before charging anyone. Infra cost and customer charge are tracked
separately on every ledger entry.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

DEFAULT_PRICING = {
    'placeholder': True,
    'currency': 'USD',
    'compute_tiers': {
        # tier: infra $/hour (what we pay), customer $/hour (what we charge)
        'cpu-local': {'infra_per_hour': '0.00', 'customer_per_hour': '0.00', 'provider': 'local', 'speedup': 1.0},
        'cpu-4': {'infra_per_hour': '0.20', 'customer_per_hour': '0.30', 'provider': 'modal', 'speedup': 1.0},
        'nvidia-t4': {'infra_per_hour': '0.60', 'customer_per_hour': '0.85', 'provider': 'modal', 'speedup': 8.0},
        'nvidia-a10g': {'infra_per_hour': '1.10', 'customer_per_hour': '1.55', 'provider': 'modal', 'speedup': 14.0},
        'nvidia-a100-40gb': {'infra_per_hour': '2.10', 'customer_per_hour': '2.95', 'provider': 'lambda', 'speedup': 30.0},
    },
    'training_platform_fee': '0.50',  # per completed job
    'inference_per_1k': {'semantic_segmentation': '2.00', 'instance_segmentation': '3.00',
                         'node_classification': '0.50', 'edge_classification': '0.50'},
    'inference_infra_per_1k': {'semantic_segmentation': '0.40', 'instance_segmentation': '0.60',
                               'node_classification': '0.05', 'edge_classification': '0.05'},
    'dedicated_hosting_per_hour': '1.20',
    'storage_per_gb_month': '0.03',
}

# Rough CPU seconds per (epoch x item) on the reference 4-core dev machine, measured from local runs
# (see docs/kentucky/TEST_RESULTS.md). Used only to produce an estimate RANGE.
CPU_SECONDS_PER_EPOCH_ITEM = {
    'seg-lraspp-mbv3': 1.2, 'seg-segformer-b0': 1.5, 'inst-maskrcnn-mbv3': 3.5, 'inst-maskrcnn-r50-v2': 25.0,
    'gnn-sage-node': 0.02, 'gnn-gat-node': 0.05, 'gnn-gcn-node': 0.02, 'gnn-sage-edge': 0.04,
}

Q = Decimal('0.0001')


def pricing() -> dict:
    p = dict(DEFAULT_PRICING)
    p.update(getattr(settings, 'KA_PRICING', None) or {})
    return p


def tier(name: str) -> dict:
    t = pricing()['compute_tiers'].get(name)
    if t is None:
        raise ValueError(f'Unknown compute tier {name}')
    return t


def estimate_training(catalog_id: str, config: dict, n_items: int, gpu_type: str) -> dict:
    t = tier(gpu_type)
    per = CPU_SECONDS_PER_EPOCH_ITEM.get(catalog_id, 2.0)
    items = n_items * (config.get('crops_per_sheet', 1) if catalog_id.startswith(('seg-', 'inst-')) else 1)
    base_s = per * config['epochs'] * max(items, 1) / float(t['speedup'])
    overhead_s = 30 if t['provider'] == 'local' else 180  # provisioning + image pull + upload
    lo, hi = base_s * 0.6 + overhead_s, min(base_s * 1.8 + overhead_s, config.get('max_runtime_s', 3600))
    hi = max(hi, lo)
    rate_c, rate_i = Decimal(t['customer_per_hour']), Decimal(t['infra_per_hour'])
    fee = Decimal(pricing()['training_platform_fee']) if t['provider'] != 'local' else Decimal('0')
    cap_hours = Decimal(config.get('max_runtime_s', 3600)) / Decimal(3600)
    return {
        'gpu_type': gpu_type, 'provider': t['provider'], 'seconds_low': round(lo), 'seconds_high': round(hi),
        'customer_cost_low': str((rate_c * Decimal(lo) / 3600 + fee).quantize(Q, ROUND_HALF_UP)),
        'customer_cost_high': str((rate_c * Decimal(hi) / 3600 + fee).quantize(Q, ROUND_HALF_UP)),
        'infra_cost_high': str((rate_i * Decimal(hi) / 3600).quantize(Q, ROUND_HALF_UP)),
        'max_charge_at_runtime_limit': str((rate_c * cap_hours + fee).quantize(Q, ROUND_HALF_UP)),
        'platform_fee': str(fee), 'pricing_is_placeholder': bool(pricing().get('placeholder')),
        'note': 'Estimate range; billed on actual runtime, capped by the authorized maximum.',
    }


def training_charge(gpu_type: str, seconds: float, completed: bool) -> dict:
    t = tier(gpu_type)
    hours = Decimal(str(seconds)) / Decimal(3600)
    infra = (Decimal(t['infra_per_hour']) * hours).quantize(Q, ROUND_HALF_UP)
    cust = (Decimal(t['customer_per_hour']) * hours).quantize(Q, ROUND_HALF_UP)
    fee = Decimal(pricing()['training_platform_fee']) if (completed and t['provider'] != 'local') else Decimal('0')
    return {'infra': infra, 'compute_charge': cust, 'platform_fee': fee}


def inference_charge(task: str, n: int = 1) -> tuple[Decimal, Decimal]:
    p = pricing()
    c = Decimal(p['inference_per_1k'].get(task, '1.00')) * n / 1000
    i = Decimal(p['inference_infra_per_1k'].get(task, '0.20')) * n / 1000
    return i.quantize(Decimal('0.000001')), c.quantize(Decimal('0.000001'))
