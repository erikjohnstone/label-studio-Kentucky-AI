"""Train-screen estimates match what the platform measured, and the runtime limit grows with the job."""

from kentucky.billing import pricing
from kentucky.training import config as tcfg

# (catalog id, training sheets, measured CPU seconds) from benchmark jobs run through the platform
MEASURED = [('seg-lraspp-mbv3', 9, 368), ('seg-dinov2-s', 8, 2332), ('seg-dinov2-s', 9, 3187), ('det-dfine-s', 8, 794),
            ('det-rtdetrv2-r18', 9, 1593), ('inst-maskrcnn-mbv3', 8, 2208)]


def test_estimate_brackets_measured_runtime():
    for cid, n, real in MEASURED:
        cfg = tcfg.validate(cid, {}, {'train_items': n})
        cfg['max_runtime_s'] = pricing.runtime_cap(cid, cfg, n, 'cpu-local')
        est = pricing.estimate_training(cid, cfg, n, 'cpu-local')
        assert est['seconds_low'] <= real <= est['seconds_high'], (cid, n, real, est['seconds_low'], est['seconds_high'])
        assert cfg['max_runtime_s'] >= 1.5 * real, (cid, cfg['max_runtime_s'], real)  # would not have timed out


def test_runtime_cap_bounds_and_estimate_uses_same_settings_as_the_job():
    small = tcfg.validate('gnn-gps-node', {}, {'train_items': 3})
    assert pricing.runtime_cap('gnn-gps-node', small, 3, 'cpu-local') == 3600
    big = tcfg.validate('seg-dinov2-s', {}, {'train_items': 200})
    assert pricing.runtime_cap('seg-dinov2-s', big, 200, 'cpu-local') == 24 * 3600
    assert tcfg.validate('seg-lraspp-mbv3', {}, {'train_items': 2})['crops_per_sheet'] == 12  # tiny sets get more crops
    assert tcfg.validate('seg-lraspp-mbv3', {}, {'train_items': 9})['crops_per_sheet'] == 8
    assert tcfg.validate('seg-lraspp-mbv3', {'crops_per_sheet': 4}, {'train_items': 2})['crops_per_sheet'] == 4
