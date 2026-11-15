"""Training job orchestration: validation, authorization, queueing, worker loop, recovery, registration.

State machine (persisted on TrainingJob.status, every transition appended to status_history):

    CREATED --validate--> VALIDATING --ok--> CREATED(awaiting authorization) --authorize--> QUEUED
    QUEUED --claim--> PROVISIONING --launch--> PREPARING --runner--> TRAINING --> EVALUATING --> SAVING --> COMPLETED
    any active state --> FAILED | CANCELLED | TIMED_OUT

Training never runs inside an HTTP request: the API only creates/authorizes jobs; ``ka_worker``
(management command) claims and supervises them.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import time
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .. import catalog, storage
from ..billing import ledger, pricing
from ..models import (
    TERMINAL_STATES,
    DatasetVersion,
    JobStatus,
    LedgerEntry,
    ModelVersion,
    RegisteredModel,
    TrainingJob,
)
from ..training import config as tcfg
from .providers.base import PaidComputeNotAuthorized, ProviderError, ProviderNotConfigured, get_provider

logger = logging.getLogger(__name__)
WORKER_ID = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}'
HEARTBEAT_STALE_S = int(os.environ.get('KA_HEARTBEAT_STALE_S', 600))
GLOBAL_CONCURRENCY = int(os.environ.get('KA_MAX_CONCURRENT_JOBS', 2))
ORG_CONCURRENCY = int(os.environ.get('KA_MAX_CONCURRENT_JOBS_PER_ORG', 1))
RUNTIME_GRACE_S = int(os.environ.get('KA_RUNTIME_GRACE_S', 60))
ACTIVE = [JobStatus.PROVISIONING, JobStatus.PREPARING, JobStatus.TRAINING, JobStatus.EVALUATING, JobStatus.SAVING]


class JobError(ValueError):
    pass


def runs_root() -> Path:
    r = Path(getattr(settings, 'KA_RUNS_ROOT', None) or os.path.join(settings.BASE_DATA_DIR, 'ka_runs'))
    r.mkdir(parents=True, exist_ok=True)
    return r


def code_version() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=Path(__file__).parent, stderr=subprocess.DEVNULL,
                                       timeout=5).decode().strip()
    except Exception:  # noqa: BLE001
        return 'unknown'


def transition(job: TrainingJob, status: str, **fields):
    job.status = status
    job.status_history = list(job.status_history) + [{'status': status, 'at': timezone.now().isoformat(),
                                                      **{k: v for k, v in fields.items() if k == 'reason'}}]
    for k, v in fields.items():
        if k != 'reason':
            setattr(job, k, v)
    if status in TERMINAL_STATES and not job.finished_at:
        job.finished_at = timezone.now()
    job.save()


# --------------------------------------------------------------------------------- create / validate
def create_job(org, user, version: DatasetVersion, catalog_id: str, init: str, overrides=None, base_model_version=None,
               gpu_type='cpu-local', name='') -> TrainingJob:
    if version.organization_id != org.id:
        raise JobError('Dataset version not found')
    entry = catalog.get(catalog_id)
    if entry is None:
        raise JobError(f'Unknown model {catalog_id}')
    job = TrainingJob.objects.create(
        organization=org, dataset_version=version, task=entry['task'], catalog_id=catalog_id, init=init,
        config={}, created_by=user, name=name or f'{version.dataset.name} v{version.version} / {entry["name"]}'[:200],
        gpu_type=gpu_type, code_version=code_version(), base_model_version=base_model_version,
        status_history=[{'status': JobStatus.CREATED, 'at': timezone.now().isoformat()}],
    )
    transition(job, JobStatus.VALIDATING)
    try:
        cfg = _validate(job, org, version, entry, init, overrides, base_model_version, gpu_type)
    except (JobError, tcfg.ConfigError, ValueError) as e:
        transition(job, JobStatus.FAILED, error=f'Validation failed: {e}', reason='validation')
        return job
    n_items = len(version.splits['train'])
    est = pricing.estimate_training(catalog_id, cfg, n_items, gpu_type)
    job.config, job.seed, job.estimate = cfg, cfg['seed'], est
    job.provider = est['provider']
    job.max_runtime_s = cfg['max_runtime_s']
    transition(job, JobStatus.CREATED, reason='validated; awaiting authorization')
    return job


CONTINUE_LR_FACTOR = 0.3  # continuing from your own model: smaller steps so it refines rather than relearns


def _validate(job, org, version, entry, init, overrides, base_mv, gpu_type):
    ready = (version.readiness or {}).get('ready_for', {})
    if not ready.get(entry['task']):
        raise JobError(f'Dataset version {version.version} is not ready for {entry["task"]} (see readiness report)')
    if (version.readiness or {}).get('blockers'):
        raise JobError('Dataset version has blocking quality issues')
    opt = catalog.init_option(entry, init)
    if opt is None:
        raise JobError(f'Init "{init}" is not available for {entry["id"]}')
    if init == 'checkpoint':
        if base_mv is None or base_mv.organization_id != org.id:
            raise JobError('Base checkpoint not found')
        if base_mv.model.catalog_id != entry['id']:
            raise JobError('Base checkpoint architecture does not match the selected model')
        if not storage.exists(base_mv.artifact_key):
            raise JobError('Base checkpoint weights are missing from storage')
    t = pricing.tier(gpu_type)
    if t['provider'] == 'local' and not entry.get('cpu_trainable'):
        raise JobError(f'{entry["name"]} is not CPU-trainable; choose a GPU tier')
    n = len(version.splits['train'])
    cfg = tcfg.validate(entry['id'], overrides, {'train_items': n})
    if init == 'checkpoint' and 'lr' not in (overrides or {}):
        cfg['lr'] = float(f"{cfg['lr'] * CONTINUE_LR_FACTOR:.3g}")  # full LR undid a trained DINOv2 in one epoch (job 36)
    if 'max_runtime_s' not in (overrides or {}):
        cfg['max_runtime_s'] = pricing.runtime_cap(entry['id'], cfg, n, gpu_type)
    return cfg


# --------------------------------------------------------------------------------- authorization
def authorize(job: TrainingJob, user, max_cost_usd=None) -> TrainingJob:
    if job.status != JobStatus.CREATED:
        raise JobError(f'Job is {job.status}; only validated jobs awaiting authorization can be authorized')
    est = job.estimate
    cap = Decimal(str(max_cost_usd if max_cost_usd is not None else est['max_charge_at_runtime_limit']))
    if cap < Decimal(est['customer_cost_low']):
        raise JobError(f'Authorized maximum ${cap} is below the low estimate ${est["customer_cost_low"]}')
    if cap > 0:
        ok, msg = ledger.check_spend(job.organization, cap)
        if not ok:
            raise JobError(msg)
        acct = ledger.account(job.organization)
        if acct.payment_method_status == 'none' and acct.prepaid_credit_usd < cap:
            raise JobError('A payment method (or prepaid credit) is required for paid compute')
    try:
        p = get_provider(job.provider)
        p.check_available()
    except (PaidComputeNotAuthorized, ProviderNotConfigured) as e:
        raise JobError(str(e))
    transition(job, JobStatus.QUEUED, authorized_by=user, authorized_at=timezone.now(), max_cost_usd=cap, reason='authorized')
    return job


def request_cancel(job: TrainingJob):
    if job.status in TERMINAL_STATES:
        return job
    if job.status in (JobStatus.CREATED, JobStatus.QUEUED, JobStatus.VALIDATING):
        transition(job, JobStatus.CANCELLED, cancel_requested=True, reason='cancelled before start')
        return job
    job.cancel_requested = True
    job.save(update_fields=['cancel_requested'])
    return job


# --------------------------------------------------------------------------------- worker
def claim_next() -> TrainingJob | None:
    active = TrainingJob.objects.filter(status__in=ACTIVE)
    if active.count() >= GLOBAL_CONCURRENCY:
        return None
    busy_orgs = {}
    for j in active.values('organization_id'):
        busy_orgs[j['organization_id']] = busy_orgs.get(j['organization_id'], 0) + 1
    for job in TrainingJob.objects.filter(status=JobStatus.QUEUED).order_by('created_at'):
        if busy_orgs.get(job.organization_id, 0) >= ORG_CONCURRENCY:
            continue
        # optimistic claim works on SQLite and Postgres
        n = TrainingJob.objects.filter(pk=job.pk, status=JobStatus.QUEUED).update(status=JobStatus.PROVISIONING, worker_id=WORKER_ID)
        if n == 1:
            job.refresh_from_db()
            transition(job, JobStatus.PROVISIONING, attempt=job.attempt + 1, reason=f'claimed by {WORKER_ID}')
            return job
    return None


def prepare_job_dir(job: TrainingJob) -> Path:
    from ..datasets.export import export_version

    d = runs_root() / f'org_{job.organization_id}' / f'job_{job.id}_a{job.attempt}'
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    export_version(job.dataset_version, d / 'bundle')
    base = None
    if job.init == 'checkpoint' and job.base_model_version_id:
        base = d / 'base.pt'
        base.write_bytes(storage.get_bytes(job.base_model_version.artifact_key, job.organization_id))
    spec = {'job_id': job.id, 'task': job.task, 'catalog_id': job.catalog_id, 'init': job.init, 'config': job.config,
            # paths are relative to the job directory so the same spec runs on any provider (local, Modal, Lambda)
            'bundle_dir': 'bundle', 'out_dir': 'artifacts', 'base_checkpoint': 'base.pt' if base else None,
            'max_runtime_s': job.max_runtime_s}
    (d / 'spec.json').write_text(json.dumps(spec, indent=1))
    return d


def start(job: TrainingJob):
    try:
        provider = get_provider(job.provider)
        d = prepare_job_dir(job)
        pid = provider.launch(job, str(d))
    except (ProviderError, PaidComputeNotAuthorized) as e:
        _fail(job, f'Provider error: {e}', retryable=True)
        return
    except Exception as e:  # noqa: BLE001
        logger.exception('job start failed')
        _fail(job, f'Preparation failed: {type(e).__name__}: {e}', retryable=False)
        return
    transition(job, JobStatus.PREPARING, provider_job_id=pid, job_dir=str(d), started_at=timezone.now(),
               heartbeat_at=timezone.now(), events_offset=0)


def read_events(job: TrainingJob):
    p = Path(job.job_dir) / 'events.jsonl'
    if not p.exists():
        return []
    with open(p) as f:
        f.seek(job.events_offset)
        data = f.read()
    # only consume complete lines
    if not data:
        return []
    last_nl = data.rfind('\n')
    if last_nl < 0:
        return []
    chunk = data[: last_nl + 1]
    job.events_offset += len(chunk.encode())
    out = []
    for line in chunk.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def supervise(job: TrainingJob):
    """One supervision step for an active job."""
    provider = get_provider(job.provider) if job.provider == 'local' else _safe_provider(job)
    if provider is None:
        return
    try:
        provider.sync(job, job.job_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning('sync failed for job %s: %s', job.id, e)
    terminal_event = None
    hist = list(job.metrics_history)
    for ev in read_events(job):
        t = ev.get('type')
        job.heartbeat_at = timezone.now()
        if t == 'status' and ev.get('status') in JobStatus.values and ev['status'] != job.status:
            job.save()
            transition(job, ev['status'])
            if ev['status'] == JobStatus.TRAINING:
                job.resource_usage = {**job.resource_usage, 'training_info': {k: v for k, v in ev.items() if k not in ('type', 't', 'ts', 'status')}}
            elif ev['status'] == JobStatus.PREPARING:
                job.resource_usage = {**job.resource_usage, 'device': ev.get('device'), 'torch': ev.get('torch')}
        elif t == 'metric':
            hist.append({k: v for k, v in ev.items() if k not in ('type', 'ts')})
        elif t == 'log':
            hist.append({'log': ev.get('message'), 't': ev.get('t')})
        elif t == 'checkpoint':
            job.resource_usage = {**job.resource_usage, 'checkpoints': job.resource_usage.get('checkpoints', []) + [ev.get('path')]}
        elif t in ('final', 'error', 'cancelled', 'timeout'):
            terminal_event = ev
    job.metrics_history = hist
    job.save()
    if terminal_event:
        _finish(job, provider, terminal_event)
        return
    # cancellation
    if job.cancel_requested:
        provider.cancel(job)
        if time.time() - job.heartbeat_at.timestamp() > 20:  # runner did not honour cancel in time
            provider.cleanup(job)
            _bill_and_close(job, JobStatus.CANCELLED, 'cancel requested (forced)')
        return
    # a process that is gone first: a crash or a killed machine is an infrastructure failure (retried, not
    # charged) even when it is discovered after the time limit, e.g. by a worker restarting later
    poll = provider.poll(job)
    if poll.state != 'running':
        # process gone without a terminal event -> read any last events first
        late = read_events(job)
        fin = next((e for e in late if e.get('type') in ('final', 'error', 'cancelled', 'timeout')), None)
        job.save()
        if fin:
            _finish(job, provider, fin)
            return
        provider.cleanup(job)
        _fail(job, f'Worker process exited unexpectedly (exit={poll.exit_code} {poll.detail})', retryable=True)
        return
    # runtime limit (+grace for the runner's own deadline)
    elapsed = (timezone.now() - job.started_at).total_seconds() if job.started_at else 0
    if elapsed > job.max_runtime_s + int(os.environ.get('KA_RUNTIME_GRACE_S', RUNTIME_GRACE_S)):
        provider.cleanup(job)
        _bill_and_close(job, JobStatus.TIMED_OUT, f'exceeded max runtime {job.max_runtime_s}s')
        return
    if job.heartbeat_at and (timezone.now() - job.heartbeat_at).total_seconds() > HEARTBEAT_STALE_S:
        provider.cleanup(job)
        _fail(job, f'No heartbeat for {HEARTBEAT_STALE_S}s', retryable=True)


def _safe_provider(job):
    try:
        return get_provider(job.provider)
    except Exception as e:  # noqa: BLE001
        _fail(job, f'Provider unavailable: {e}', retryable=False)
        return None


def _finish(job, provider, ev):
    t = ev['type']
    if t == 'final':
        try:
            mv = register_model(job, ev)
        except Exception as e:  # noqa: BLE001
            logger.exception('registration failed')
            provider.cleanup(job)
            _fail(job, f'Saving model failed: {e}', retryable=False)
            return
        provider.cleanup(job)
        job.final_metrics = ev['metrics']
        _bill_and_close(job, JobStatus.COMPLETED, f'registered model version {mv.id}')
    elif t == 'cancelled':
        provider.cleanup(job)
        _bill_and_close(job, JobStatus.CANCELLED, 'cancelled by user')
    elif t == 'timeout':
        provider.cleanup(job)
        _bill_and_close(job, JobStatus.TIMED_OUT, ev.get('message', 'timeout'))
    else:
        provider.cleanup(job)
        # training code errors (bad data, missing weights ...) are not retried; infrastructure errors (disk full) are
        _fail(job, ev.get('message', 'error'), retryable=bool(ev.get('infra')), traceback=ev.get('traceback'))


def _fail(job, msg, retryable: bool, traceback=None):
    job.error = msg + (f'\n{traceback}' if traceback else '')
    if retryable and job.attempt < job.max_attempts and not job.cancel_requested:
        job.save(update_fields=['error'])
        transition(job, JobStatus.QUEUED, reason=f'retry after infrastructure failure: {msg[:200]}')
        return
    job.save(update_fields=['error'])
    _bill_and_close(job, JobStatus.FAILED, msg[:300], infra_failure=retryable)


def _bill_and_close(job, status, reason, infra_failure=False):
    """Billing policy: completed / cancelled / timed-out jobs pay actual compute (capped at the authorized
    maximum). Jobs that failed because of platform or provider faults are not charged."""
    runtime = (timezone.now() - job.started_at).total_seconds() if job.started_at else 0.0
    job.resource_usage = {**job.resource_usage, 'runtime_s': round(runtime, 2), 'gpu_type': job.gpu_type}
    if job.started_at and not infra_failure:
        ch = pricing.training_charge(job.gpu_type, runtime, completed=(status == JobStatus.COMPLETED))
        compute = min(ch['compute_charge'], job.max_cost_usd) if job.max_cost_usd else ch['compute_charge']
        ledger.record(job.organization, LedgerEntry.Kind.TRAINING_COMPUTE, f'job:{job.id}:compute', runtime / 3600, 'gpu_hour',
                      ch['infra'], compute, 'training_job', job.id, f'Training compute {job.gpu_type} ({status})')
        if ch['platform_fee'] > 0:
            ledger.record(job.organization, LedgerEntry.Kind.TRAINING_PLATFORM_FEE, f'job:{job.id}:platform_fee', 1, 'job', 0,
                          ch['platform_fee'], 'training_job', job.id, 'Training platform fee')
    elif job.started_at and infra_failure:
        ch = pricing.training_charge(job.gpu_type, runtime, completed=False)
        ledger.record(job.organization, LedgerEntry.Kind.TRAINING_COMPUTE, f'job:{job.id}:compute', runtime / 3600, 'gpu_hour',
                      ch['infra'], 0, 'training_job', job.id, 'Infrastructure failure - not charged')
    job.save()
    transition(job, status, reason=reason)
    cleanup_job_dir(job)


def cleanup_job_dir(job) -> int:
    """Free the working copy of a finished job: dataset bundle, base checkpoint and checkpoints (the registered model
    is already in object storage). Keeps spec, events, logs and metrics for the run's record. Returns bytes freed."""
    d = Path(job.job_dir) if job.job_dir else None
    if d is None or not d.exists() or job.status not in TERMINAL_STATES:
        return 0
    freed = 0
    for p in [d / 'bundle', d / 'base.pt', *sorted((d / 'artifacts').glob('*.pt'))]:
        if p.is_dir():
            freed += sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            freed += p.stat().st_size
            p.unlink()
    return freed


def register_model(job, ev) -> ModelVersion:
    art = Path(job.job_dir) / ev['artifact']
    sha = storage.sha256_file(art)
    if sha != ev.get('sha256'):
        raise ValueError('artifact checksum mismatch')
    entry = catalog.get(job.catalog_id)
    if entry is None:  # the worker process predates this catalog entry: deploy rule = restart the worker with the web
        raise RuntimeError(f'This worker does not know model "{job.catalog_id}" (it is running older code). Restart the worker '
                           '(ka_worker) after deploying, then train again.')
    base_license = job.base_model_version.license if job.base_model_version_id else None
    ok, why = catalog.deployable(job.catalog_id, job.init, base_license)
    with transaction.atomic():
        name = f'{job.dataset_version.dataset.name}-{job.catalog_id}'[:200]
        if job.base_model_version_id:
            rm = job.base_model_version.model
        else:
            rm, _ = RegisteredModel.objects.get_or_create(organization=job.organization, name=name,
                                                          defaults={'task': job.task, 'catalog_id': job.catalog_id})
        last = rm.versions.order_by('-version').first()
        v = (last.version + 1) if last else 1
        k = storage.key(job.organization_id, 'models', rm.id, f'v{v}', 'model.pt')
        storage.put_file(k, art)
        mfile = Path(job.job_dir) / 'artifacts' / 'metrics.json'
        if mfile.exists():
            storage.put_file(storage.key(job.organization_id, 'models', rm.id, f'v{v}', 'metrics.json'), mfile)
        classes = ev['metrics'].get('classes', [])
        io_schema = _io_schema(job.task)
        return ModelVersion.objects.create(
            organization=job.organization, model=rm, version=v, training_job=job, dataset_version=job.dataset_version,
            artifact_key=k, artifact_sha256=sha, metrics=ev['metrics'], input_schema=io_schema[0], output_schema=io_schema[1],
            label_map={str(i): c for i, c in enumerate(classes)},
            license={'catalog_id': job.catalog_id, 'architecture': entry['architecture'],
                     'implementation_license': entry['implementation_license'], 'init': job.init,
                     'checkpoint_license': (catalog.init_option(entry, job.init) or {}).get('checkpoint_license'),
                     'commercially_deployable': ok, 'reason': why,
                     'base_model_version': job.base_model_version_id},
        )


def _io_schema(task):
    if task in ('semantic_segmentation', 'instance_segmentation'):
        return ({'oneOf': [{'image': 'base64 PNG/JPG'}, {'sheet_id': 'int (dataset sheet in your org)'}]},
                {'predictions': [{'label': 'str', 'confidence': 'float', 'bbox': '[x,y,w,h] image px',
                                  'polygon': '[[x,y]] image px', 'polygon_source': '[[x,y]] source units', 'page': 'int'}]})
    return ({'oneOf': [{'graph': 'ka graph JSON (nodes/edges with features)'}, {'sheet_id': 'int'}]},
            {'nodes': [{'id': 'str', 'label': 'str', 'confidence': 'float', 'probabilities': 'dict', 'primitive_ids': '[str]'}],
             'edges': [{'id': 'str', 'source': 'str', 'target': 'str', 'label': 'str', 'confidence': 'float'}]})


def recover():
    """Crash recovery on worker start: adopt live local processes, requeue/fail lost ones."""
    for job in TrainingJob.objects.filter(status__in=ACTIVE):
        if job.status == JobStatus.PROVISIONING and not job.provider_job_id:
            _fail(job, 'Worker died during provisioning', retryable=True)
            continue
        try:
            p = get_provider(job.provider)
            st = p.poll(job)
        except Exception as e:  # noqa: BLE001
            _fail(job, f'Recovery failed: {e}', retryable=True)
            continue
        if st.state == 'running':
            TrainingJob.objects.filter(pk=job.pk).update(worker_id=WORKER_ID)  # adopt
        else:
            job.refresh_from_db()
            supervise(job)


def tick() -> int:
    """One scheduler iteration. Returns number of active jobs."""
    while True:
        j = claim_next()
        if j is None:
            break
        start(j)
    n = 0
    for job in TrainingJob.objects.filter(status__in=ACTIVE):
        if job.status == JobStatus.PROVISIONING:
            continue
        supervise(job)
        n += 1
    from ..billing import hosting

    hosting.accrue_all()  # always-on deployments: hourly hosting charges
    return n


def run_until_idle(timeout_s=1800, interval=1.0):
    """Used by tests and `ka_worker --until-idle`."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        n = tick()
        if n == 0 and not TrainingJob.objects.filter(status=JobStatus.QUEUED).exists():
            return
        time.sleep(interval)
    raise TimeoutError('jobs still running')
