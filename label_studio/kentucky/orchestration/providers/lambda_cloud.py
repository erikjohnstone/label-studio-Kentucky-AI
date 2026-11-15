"""Lambda Cloud adapter (rented GPU instances, for long or multi-GPU runs). NOT exercised against real Lambda yet:
tested end to end against a fake Lambda API and an emulated S3 bucket (tests/test_lambda_provider.py).

How a job runs:
1. ``launch`` uploads the job directory (spec + dataset bundle + base checkpoint) and the Django-free training
   package to the org's prefix in the S3/R2 bucket, then launches one instance through the Lambda Cloud API
   (``POST /instance-operations/launch``) with a cloud-init ``user_data`` script.
2. The script downloads both with presigned URLs, runs ``kentucky.training.remote_agent`` (which runs the same
   ``kentucky.training.runner`` as every provider), streams ``events.jsonl`` back, uploads artifacts and
   ``done.json``, then powers the instance off. The instance never receives platform credentials.
3. ``poll`` reads ``done.json`` (exit code) and the instance state; ``sync`` copies events/artifacts back;
   ``cleanup`` always terminates the instance (idempotent), so nothing is left running and billing.

Requires: ``LAMBDA_API_KEY``, ``KA_LAMBDA_SSH_KEY`` (name of an SSH key registered with Lambda — the API needs one),
``KA_LAMBDA_REGION``, the S3/R2 storage backend, and ``KA_ENABLE_PAID_COMPUTE=1``.
"""

from __future__ import annotations

import io
import json
import os
import tarfile
from pathlib import Path

from django.conf import settings

from ... import storage
from .base import PollResult, Provider, ProviderError, ProviderNotConfigured

API = os.environ.get('KA_LAMBDA_API_BASE', 'https://cloud.lambda.com/api/v1')  # cloud.lambda.ai is deprecated (OpenAPI v1.10.0)
GPU_MAP = {'nvidia-a100-40gb': 'gpu_1x_a100_sxm4', 'nvidia-a10g': 'gpu_1x_a10', 'nvidia-t4': 'gpu_1x_a10'}
PKG_ROOT = Path(__file__).resolve().parents[2]  # .../kentucky
# Lambda Stack images ship CUDA PyTorch; only the graph / geometry extras are installed on boot.
BOOT_PIP = 'torch_geometric==2.8.1 shapely==2.2.0 opencv-python-headless==5.0.0.93 pillow requests'


def _code_tarball() -> bytes:
    """The training package only (no Django app, no secrets): kentucky/__init__.py + kentucky/training/*.py."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        tf.add(PKG_ROOT / '__init__.py', arcname='kentucky/__init__.py')
        for p in sorted((PKG_ROOT / 'training').glob('*.py')):
            tf.add(p, arcname=f'kentucky/training/{p.name}')
    return buf.getvalue()


def user_data(urls: dict, max_runtime_s: int) -> str:
    q = lambda s: "'" + s.replace("'", "'\\''") + "'"  # noqa: E731 - shell single-quote
    return '\n'.join([
        '#!/bin/bash',
        '# Kentucky AI training job bootstrap (cloud-init). Powers the instance off when the job ends.',
        'set -u',
        'exec > /var/log/ka-agent.log 2>&1',
        f'trap "shutdown -h now" EXIT',
        'mkdir -p /opt/ka/code && cd /opt/ka',
        f'curl -fsSL --retry 5 -o code.tgz {q(urls["code"])} && tar -xzf code.tgz -C /opt/ka/code',
        f'python3 -m pip install --quiet {BOOT_PIP}',
        'export PYTHONPATH=/opt/ka/code',
        'python3 -m kentucky.training.remote_agent --workdir /opt/ka/run '
        f'--bundle {q(urls["bundle"])} --events {q(urls["events"])} --artifacts {q(urls["artifacts"])} '
        f'--done {q(urls["done"])} --max-runtime {int(max_runtime_s)}',
    ]) + '\n'


class LambdaProvider(Provider):
    name = 'lambda'
    paid = True

    def _key(self):
        k = os.environ.get('LAMBDA_API_KEY') or getattr(settings, 'KA_LAMBDA_API_KEY', '')
        if not k:
            raise ProviderNotConfigured('LAMBDA_API_KEY not configured')
        return k

    def check_available(self):
        self._key()
        if not getattr(settings, 'KA_LAMBDA_SSH_KEY', '') and not os.environ.get('KA_LAMBDA_SSH_KEY'):
            raise ProviderNotConfigured('KA_LAMBDA_SSH_KEY (an SSH key name registered with Lambda) is required to launch')
        if storage.backend() != 's3':
            raise ProviderNotConfigured('Lambda jobs exchange files through the S3/R2 storage backend (KA_STORAGE_BACKEND=s3)')

    def _req(self, method, path, **kw):
        import requests

        r = requests.request(method, API + path, headers={'Authorization': f'Bearer {self._key()}'}, timeout=30, **kw)
        if r.status_code >= 400:
            raise ProviderError(f'Lambda API {method} {path}: {r.status_code} {r.text[:300]}')
        return r.json()

    @staticmethod
    def _prefix(job):
        return storage.key(job.organization_id, 'jobs', f'job_{job.id}_a{job.attempt}')

    def launch(self, job, job_dir):
        self.check_available()
        pre = self._prefix(job)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tf:
            tf.add(job_dir, arcname='job', filter=lambda ti: None if ti.name.endswith(('events.jsonl', 'stdout.log')) else ti)
        storage.put_bytes(f'{pre}/bundle.tar.gz', buf.getvalue())
        storage.put_bytes(f'{pre}/code.tar.gz', _code_tarball())
        ttl = int(job.max_runtime_s) + 3 * 3600
        urls = {'bundle': storage.presign(f'{pre}/bundle.tar.gz', 'get', ttl), 'code': storage.presign(f'{pre}/code.tar.gz', 'get', ttl),
                'events': storage.presign(f'{pre}/events.jsonl', 'put', ttl), 'artifacts': storage.presign(f'{pre}/artifacts.tar.gz', 'put', ttl),
                'done': storage.presign(f'{pre}/done.json', 'put', ttl)}
        body = {'region_name': getattr(settings, 'KA_LAMBDA_REGION', None) or os.environ.get('KA_LAMBDA_REGION', 'us-east-1'),
                'instance_type_name': GPU_MAP.get(job.gpu_type, 'gpu_1x_a10'),
                'ssh_key_names': [getattr(settings, 'KA_LAMBDA_SSH_KEY', None) or os.environ.get('KA_LAMBDA_SSH_KEY')],  # exactly one key
                'name': f'ka-job-{job.id}', 'user_data': user_data(urls, job.max_runtime_s)}
        data = self._req('POST', '/instance-operations/launch', json=body)
        ids = data.get('data', {}).get('instance_ids', [])
        if not ids:
            raise ProviderError('Lambda launch returned no instance id')
        return f'lambda:{ids[0]}'

    def poll(self, job):
        pre = self._prefix(job)
        if storage.exists(f'{pre}/done.json'):
            done = json.loads(storage.get_bytes(f'{pre}/done.json'))
            return PollResult('exited', int(done.get('exit_code', 1)))
        iid = job.provider_job_id.split(':', 1)[1]
        st = self._req('GET', f'/instances/{iid}').get('data', {}).get('status')
        if st in ('terminated', 'terminating', 'unhealthy'):
            return PollResult('exited', 1, f'instance {st} before the job finished')
        return PollResult('running', detail=st or '')

    def sync(self, job, job_dir):
        pre = self._prefix(job)
        if storage.exists(f'{pre}/events.jsonl'):
            Path(job_dir, 'events.jsonl').write_bytes(storage.get_bytes(f'{pre}/events.jsonl'))
        if storage.exists(f'{pre}/artifacts.tar.gz'):
            with tarfile.open(fileobj=io.BytesIO(storage.get_bytes(f'{pre}/artifacts.tar.gz')), mode='r:gz') as tf:
                tf.extractall(job_dir, filter='data')

    def cancel(self, job):
        self.cleanup(job)

    def cleanup(self, job):
        if job.provider_job_id and job.provider_job_id.startswith('lambda:'):
            iid = job.provider_job_id.split(':', 1)[1]
            try:
                self._req('POST', '/instance-operations/terminate', json={'instance_ids': [iid]})
            except ProviderError as e:
                if '404' not in str(e) and 'not found' not in str(e).lower():  # already gone is fine
                    raise
