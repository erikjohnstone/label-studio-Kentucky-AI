"""Lambda Cloud provider end to end without touching Lambda or a real bucket: a fake Lambda API records the launch,
the cloud-init script's agent is run locally against an emulated S3 bucket (moto), and the orchestrator completes
the job from what the "instance" uploaded — real GNN training, artifact, registration, billing, termination."""

import re
import shlex
import tarfile
import io
from decimal import Decimal

import pytest

moto = pytest.importorskip('moto')

from kentucky.billing import ledger  # noqa: E402
from kentucky.datasets.versioning import create_version  # noqa: E402
from kentucky.models import JobStatus, LedgerEntry, ModelVersion  # noqa: E402
from kentucky.orchestration import service as S  # noqa: E402
from kentucky.orchestration.providers.lambda_cloud import LambdaProvider  # noqa: E402

from .test_training_failures import _wait  # noqa: E402


@pytest.fixture
def lambda_env(settings, monkeypatch, org_a):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'test')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'test')
    monkeypatch.setenv('LAMBDA_API_KEY', 'secret-lambda-key')
    monkeypatch.setenv('KA_ENABLE_PAID_COMPUTE', '1')
    mock = getattr(moto, 'mock_aws', None) or moto.mock_s3
    with mock():
        import boto3

        from kentucky import storage

        settings.KA_STORAGE_BACKEND, settings.KA_S3_BUCKET, settings.KA_S3_REGION = 's3', 'ka-runs', 'us-east-1'
        settings.KA_LAMBDA_SSH_KEY = 'ka-orchestrator'
        storage.reset_client()
        boto3.client('s3', region_name='us-east-1').create_bucket(Bucket='ka-runs')
        calls = {'launch': [], 'terminate': [], 'status': 'active'}

        def fake_req(self, method, path, **kw):
            if path == '/instance-operations/launch':
                calls['launch'].append(kw['json'])
                return {'data': {'instance_ids': ['inst-1']}}
            if path.startswith('/instances/'):
                return {'data': {'status': calls['status']}}
            if path == '/instance-operations/terminate':
                calls['terminate'].append(kw['json'])
                return {'data': {'terminated_instances': []}}
            raise AssertionError(path)

        monkeypatch.setattr(LambdaProvider, '_req', fake_req)
        acct = ledger.account(org_a[1])
        acct.payment_method_status = 'test_card'
        acct.save()
        yield calls
        storage.reset_client()


def _urls(script):
    line = [x for x in script.splitlines() if 'remote_agent' in x][0]
    args = shlex.split(line)
    return {args[i][2:]: args[i + 1] for i in range(len(args)) if args[i].startswith('--')}


@pytest.mark.django_db
def test_lambda_job_runs_through_the_bucket(lambda_env, labeled_dataset, org_a, tmp_path):
    from kentucky.training import remote_agent

    user, org = org_a
    v = create_version(labeled_dataset[0], user)
    j = S.create_job(org, user, v, 'gnn-sage-node', 'scratch', {'epochs': 5}, gpu_type='nvidia-a100-40gb')
    assert j.provider == 'lambda'
    S.authorize(j, user, max_cost_usd=5)
    S.tick()
    j.refresh_from_db()
    assert j.provider_job_id == 'lambda:inst-1' and len(lambda_env['launch']) == 1
    body = lambda_env['launch'][0]
    assert body['instance_type_name'] == 'gpu_1x_a100_sxm4' and body['ssh_key_names'] == ['ka-orchestrator']
    script = body['user_data']
    assert script.startswith('#!/bin/bash') and 'shutdown -h now' in script
    assert 'secret-lambda-key' not in script and 'AWS_SECRET' not in script
    u = _urls(script)
    assert set(u) >= {'bundle', 'events', 'artifacts', 'done', 'max-runtime'}
    # the code shipped to the instance is the training package only
    from kentucky import storage

    pre = f'org_{org.id}/jobs/job_{j.id}_a{j.attempt}'
    names = tarfile.open(fileobj=io.BytesIO(storage.get_bytes(f'{pre}/code.tar.gz')), mode='r:gz').getnames()
    assert names and all(n == 'kentucky/__init__.py' or n.startswith('kentucky/training/') for n in names)

    # --- the "instance": run the agent exactly as cloud-init would, against the presigned URLs
    code = remote_agent.run(u['bundle'], u['events'], u['artifacts'], u['done'], float(u['max-runtime']), str(tmp_path / 'inst'), interval=0.5)
    assert code == 0
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES, timeout=120)
    assert j.status == JobStatus.COMPLETED, j.error
    mv = ModelVersion.objects.get(training_job=j)
    assert mv.artifact_sha256 and storage.exists(mv.artifact_key) and (j.final_metrics or {}).get('headline')
    assert lambda_env['terminate'] and lambda_env['terminate'][-1] == {'instance_ids': ['inst-1']}
    assert LedgerEntry.objects.filter(idempotency_key=f'job:{j.id}:compute').count() == 1


@pytest.mark.django_db
def test_lambda_instance_lost_fails_and_terminates(lambda_env, labeled_dataset, org_a):
    user, org = org_a
    v = create_version(labeled_dataset[0], user)
    j = S.create_job(org, user, v, 'gnn-sage-node', 'scratch', {'epochs': 5}, gpu_type='nvidia-a100-40gb')
    S.authorize(j, user, max_cost_usd=5)
    S.tick()
    lambda_env['status'] = 'terminated'  # the machine disappeared before writing done.json
    j = _wait(j, lambda x: x.status in S.TERMINAL_STATES or x.attempt > 1, timeout=60)
    assert lambda_env['terminate']  # always cleaned up
    assert not ModelVersion.objects.filter(training_job=j).exists()


@pytest.mark.django_db
def test_lambda_refuses_without_bucket_or_ssh_key(settings, monkeypatch):
    from kentucky.orchestration.providers.base import ProviderNotConfigured

    monkeypatch.setenv('LAMBDA_API_KEY', 'x')
    settings.KA_STORAGE_BACKEND = 'local'
    settings.KA_LAMBDA_SSH_KEY = 'k'
    with pytest.raises(ProviderNotConfigured, match='S3/R2'):
        LambdaProvider().check_available()
    settings.KA_LAMBDA_SSH_KEY = ''
    monkeypatch.delenv('KA_LAMBDA_SSH_KEY', raising=False)
    with pytest.raises(ProviderNotConfigured, match='SSH'):
        LambdaProvider().check_available()
