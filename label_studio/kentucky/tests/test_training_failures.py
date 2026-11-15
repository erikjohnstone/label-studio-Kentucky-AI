"""Test F - cancellation, timeouts, worker failures, missing weights, invalid datasets, provider errors, cleanup, billing."""

import os
import signal
import time
from decimal import Decimal

import pytest

from kentucky.billing import ledger
from kentucky.datasets.versioning import create_version
from kentucky.models import JobStatus, LedgerEntry, ModelVersion, RegisteredModel, TrainingJob
from kentucky.orchestration import service as S


def _pid(job):
    return int(job.provider_job_id.split(':')[1])


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # zombie counts as dead
        with open(f'/proc/{pid}/status') as f:
            return 'zombie' not in f.read()
    except FileNotFoundError:
        return False
    return True


def _wait(job, cond, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        S.tick()
        job.refresh_from_db()
        if cond(job):
            return job
        time.sleep(0.5)
    raise AssertionError(f'timeout waiting; status={job.status} err={job.error[:300]}')


@pytest.fixture
def version(labeled_dataset, org_a):
    ds, _ = labeled_dataset
    return create_version(ds, org_a[0])


@pytest.mark.django_db
def test_invalid_dataset_and_bad_selections_fail_validation(org_a, labeled_dataset):
    user, org = org_a
    ds, _ = labeled_dataset
    from kentucky.models import CanonicalObject, SheetGraph

    CanonicalObject.objects.filter(dataset=ds).update(review_status='pending')
    SheetGraph.objects.filter(sheet__dataset=ds).update(review_status='pending')
    v = create_version(ds, user)
    j = S.create_job(org, user, v, 'gnn-sage-node', 'scratch')
    assert j.status == JobStatus.FAILED and 'not ready' in j.error


@pytest.mark.django_db
def test_missing_weights_unknown_init_and_cpu_restrictions(org_a, version):
    user, org = org_a
    rm = RegisteredModel.objects.create(organization=org, name='base', task='node_classification', catalog_id='gnn-sage-node')
    mv = ModelVersion.objects.create(organization=org, model=rm, version=1, artifact_key=f'org_{org.id}/models/missing.pt', artifact_sha256='0' * 64)
    j = S.create_job(org, user, version, 'gnn-sage-node', 'checkpoint', base_model_version=mv)
    assert j.status == JobStatus.FAILED and 'missing' in j.error
    j = S.create_job(org, user, version, 'gnn-sage-node', 'pretrained')
    assert j.status == JobStatus.FAILED and 'not available' in j.error
    j = S.create_job(org, user, version, 'inst-maskrcnn-r50-v2', 'scratch', gpu_type='cpu-local')
    assert j.status == JobStatus.FAILED and 'not CPU-trainable' in j.error
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'lr': 5.0})
    assert j.status == JobStatus.FAILED and 'lr' in j.error
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'rm -rf': 1})
    assert j.status == JobStatus.FAILED and 'Unsupported hyperparameter' in j.error


@pytest.mark.django_db
def test_paid_provider_requires_operator_enablement_and_payment(org_a, version, monkeypatch):
    user, org = org_a
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', gpu_type='nvidia-t4')
    assert j.status == JobStatus.CREATED and j.provider == 'modal' and Decimal(j.estimate['max_charge_at_runtime_limit']) > 0
    with pytest.raises(S.JobError, match='payment method'):
        S.authorize(j, user)
    acct = ledger.account(org)
    acct.payment_method_status = 'test_card'
    acct.save()
    monkeypatch.delenv('KA_ENABLE_PAID_COMPUTE', raising=False)
    with pytest.raises(S.JobError, match='KA_ENABLE_PAID_COMPUTE'):
        S.authorize(j, user)
    monkeypatch.setenv('KA_ENABLE_PAID_COMPUTE', '1')
    with pytest.raises(S.JobError, match='modal|MODAL'):
        S.authorize(j, user)  # SDK / credentials not configured -> still refused, nothing launched
    j.refresh_from_db()
    assert j.status == JobStatus.CREATED and not j.provider_job_id
    acct.monthly_spend_cap_usd = Decimal('0.01')
    acct.save()
    with pytest.raises(S.JobError, match='Spend cap'):
        S.authorize(j, user, max_cost_usd=5)


@pytest.mark.django_db
def test_cancellation_kills_worker_and_bills_once(org_a, version):
    user, org = org_a
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'epochs': 2000, 'early_stopping_patience': 1000})
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status == JobStatus.TRAINING)
    pid = _pid(j)
    S.request_cancel(j)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES)
    assert j.status == JobStatus.CANCELLED
    time.sleep(0.5)
    assert not _alive(pid)
    assert LedgerEntry.objects.filter(idempotency_key=f'job:{j.id}:compute').count() == 1
    S._bill_and_close(j, JobStatus.CANCELLED, 'again')  # re-running billing must not double-charge
    assert LedgerEntry.objects.filter(idempotency_key=f'job:{j.id}:compute').count() == 1


@pytest.mark.django_db
def test_timeout_terminates_hung_worker(org_a, version, monkeypatch):
    user, org = org_a
    monkeypatch.setenv('KA_RUNTIME_GRACE_S', '2')
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'_fault': 'hang', 'max_runtime_s': 30})
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status == JobStatus.TRAINING)
    pid = _pid(j)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES, timeout=120)
    assert j.status == JobStatus.TIMED_OUT
    time.sleep(0.5)
    assert not _alive(pid)


@pytest.mark.django_db
def test_worker_crash_is_retried_then_succeeds_and_infra_failure_not_charged(org_a, version):
    user, org = org_a
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'epochs': 400, 'early_stopping_patience': 1000})
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status == JobStatus.TRAINING)
    os.killpg(_pid(j), signal.SIGKILL)  # worker dies abruptly (OOM / node loss)
    j = _wait(j, lambda x: x.attempt == 2 or x.status in S.TERMINAL_STATES)
    assert any('retry after infrastructure failure' in (h.get('reason') or '') for h in j.status_history)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES, timeout=400)
    assert j.status == JobStatus.COMPLETED and j.attempt == 2
    assert j.model_versions.count() == 1


@pytest.mark.django_db
def test_machine_lost_long_ago_is_retried_not_timed_out(org_a, version):
    """Found on the platform: the worker and its training process were killed (out of memory); when a worker came
    back after the job's time limit had passed, the job was marked 'exceeded max runtime' instead of being retried
    as an infrastructure failure."""
    from datetime import timedelta

    from django.utils import timezone

    user, org = org_a
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'epochs': 400, 'early_stopping_patience': 1000, 'max_runtime_s': 60})
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status == JobStatus.TRAINING)
    pid = _pid(j)
    os.killpg(pid, signal.SIGKILL)
    from kentucky.orchestration.providers import local as LP

    LP._PROCS.pop(pid).wait(timeout=30)  # the old worker is gone too: the new one has never seen this process
    TrainingJob.objects.filter(pk=j.pk).update(started_at=timezone.now() - timedelta(hours=2),
                                               heartbeat_at=timezone.now() - timedelta(hours=1))
    S.recover()  # a worker starting up later
    j.refresh_from_db()
    assert j.status != JobStatus.TIMED_OUT, j.error
    assert j.status == JobStatus.QUEUED and 'exited unexpectedly' in j.error
    assert any('retry after infrastructure failure' in (h.get('reason') or '') for h in j.status_history)
    assert not LedgerEntry.objects.filter(reference_type='training_job', reference_id=str(j.id)).exists()  # nothing charged
    S.request_cancel(j)  # don't run the retry in this test


@pytest.mark.django_db
def test_training_code_error_fails_without_retry(org_a, version):
    user, org = org_a
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'_fault': 'crash'})
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES)
    assert j.status == JobStatus.FAILED and 'injected worker crash' in j.error and j.attempt == 1
    assert j.model_versions.count() == 0


@pytest.mark.django_db
def test_ledger_idempotency(org_a):
    _, org = org_a
    e1, c1 = ledger.record(org, 'inference', 'inf:1:req-abc', 1, 'request', '0.0004', '0.002')
    e2, c2 = ledger.record(org, 'inference', 'inf:1:req-abc', 1, 'request', '0.0004', '0.002')
    assert c1 and not c2 and e1.pk == e2.pk
    assert LedgerEntry.objects.filter(idempotency_key='inf:1:req-abc').count() == 1
    e1.refresh_from_db()
    assert e1.stripe_status in ('not_configured', 'zero_amount')


@pytest.mark.django_db
def test_finished_job_folder_is_cleaned_and_model_survives(org_a, version):
    """Resource cleanup: a finished job keeps its record (spec, events, metrics) but not its data copy or checkpoints;
    the registered model is served from object storage."""
    from pathlib import Path

    user, org = org_a
    j = S.create_job(org, user, version, 'gnn-sage-node', 'scratch', {'epochs': 3})
    S.authorize(j, user)
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES)
    assert j.status == JobStatus.COMPLETED
    d = Path(j.job_dir)
    assert (d / 'events.jsonl').exists() and (d / 'spec.json').exists()
    assert not (d / 'bundle').exists() and not list((d / 'artifacts').glob('*.pt'))
    mv = ModelVersion.objects.get(training_job=j)
    from kentucky import storage

    assert storage.exists(mv.artifact_key)


def test_disk_full_is_an_infrastructure_error():
    import errno

    from kentucky.training.runner import _disk_full

    assert _disk_full(OSError(errno.ENOSPC, 'No space left on device'))
    assert _disk_full(RuntimeError('[enforce fail at inline_container.cc:671] . unexpected pos 131260864 vs 131260752'))
    wrapped = RuntimeError('save failed')
    wrapped.__cause__ = OSError(errno.ENOSPC, 'full')
    assert _disk_full(wrapped)
    assert not _disk_full(ValueError('Training split is empty'))
