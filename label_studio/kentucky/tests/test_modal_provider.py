"""Modal provider end to end with a stand-in for the Modal SDK: spawn runs the real function body
(``kentucky.training.modal_entry.run_job``, the code deployed in deploy/modal/ka_trainer.py) into a local "volume";
the orchestrator polls the call, syncs events + checkpoint from the volume, registers the model and bills once."""

import sys
import threading
import types
from pathlib import Path

import pytest

from kentucky.billing import ledger
from kentucky.datasets.versioning import create_version
from kentucky.models import JobStatus, LedgerEntry, ModelVersion
from kentucky.orchestration import service as S

from .test_training_failures import _wait


@pytest.fixture
def fake_modal(monkeypatch, tmp_path, org_a):
    from kentucky.training.modal_entry import run_job

    vol_root = tmp_path / 'volume'
    calls, spawned = {}, []

    class Call:
        def __init__(self, cid):
            self.object_id, self.result, self.cancelled = cid, None, False

        def get(self, timeout=None):
            if self.result is None:
                raise TimeoutError()
            return self.result

        def cancel(self):
            self.cancelled = True

    class Fn:
        def __init__(self, app, name):
            self.app, self.name = app, name

        def spawn(self, job_id, bundle, max_runtime_s):
            c = Call(f'fc-{len(calls) + 1}')
            calls[c.object_id] = c
            spawned.append((self.app, self.name))
            threading.Thread(target=lambda: setattr(c, 'result', run_job(job_id, bundle, max_runtime_s, str(vol_root), interval=0.5)), daemon=True).start()
            return c

    class Entry:
        def __init__(self, path):
            self.path, self.type = path, types.SimpleNamespace(name='FILE')

    class Volume:
        @staticmethod
        def from_name(name):
            return Volume()

        def listdir(self, prefix, recursive=False):
            base = vol_root / prefix.lstrip('/')
            return [Entry('/' + str(p.relative_to(vol_root))) for p in base.rglob('*') if p.is_file()] if base.exists() else []

        def read_file(self, path):
            yield (vol_root / path.lstrip('/')).read_bytes()

    mod = types.ModuleType('modal')
    mod.Function = types.SimpleNamespace(from_name=lambda app, name: Fn(app, name))
    mod.FunctionCall = types.SimpleNamespace(from_id=lambda cid: calls[cid])
    mod.Volume = Volume
    monkeypatch.setitem(sys.modules, 'modal', mod)
    monkeypatch.setenv('MODAL_TOKEN_ID', 'x')
    monkeypatch.setenv('MODAL_TOKEN_SECRET', 'y')
    monkeypatch.setenv('KA_ENABLE_PAID_COMPUTE', '1')
    acct = ledger.account(org_a[1])
    acct.payment_method_status = 'test_card'
    acct.save()
    return {'calls': calls, 'spawned': spawned, 'volume': vol_root}


@pytest.mark.django_db
def test_modal_job_end_to_end(fake_modal, labeled_dataset, org_a):
    user, org = org_a
    v = create_version(labeled_dataset[0], user)
    j = S.create_job(org, user, v, 'gnn-sage-node', 'scratch', {'epochs': 5}, gpu_type='nvidia-t4')
    assert j.provider == 'modal'
    S.authorize(j, user, max_cost_usd=5)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES, timeout=180)
    assert j.status == JobStatus.COMPLETED, j.error
    assert fake_modal['spawned'] == [('ka-trainer', 'train_t4')]
    assert (Path(fake_modal['volume']) / 'jobs' / str(j.id) / 'events.jsonl').exists()
    mv = ModelVersion.objects.get(training_job=j)
    assert mv.artifact_sha256 and (j.final_metrics or {}).get('headline')
    assert LedgerEntry.objects.filter(idempotency_key=f'job:{j.id}:compute').count() == 1
    assert all(c.cancelled for c in fake_modal['calls'].values())  # cleanup releases the container
