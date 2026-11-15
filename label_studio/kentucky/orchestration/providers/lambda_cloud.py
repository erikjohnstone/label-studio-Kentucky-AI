"""Lambda Cloud adapter (secondary path, for long multi-GPU runs). NOT exercised against real Lambda yet.

Implements instance provisioning + guaranteed termination via the Lambda Cloud API
(``POST /instance-operations/launch``, ``GET /instances/{id}``, ``POST /instance-operations/terminate``).
Running the training container on the instance requires an SSH bootstrap step that is NOT
implemented yet (documented in docs/kentucky/GPU_PROVIDERS.md); ``launch`` therefore refuses to
start unless ``KA_LAMBDA_BOOTSTRAP`` is implemented/enabled, so no instance can be left idle and billing.
"""

from __future__ import annotations

import os

from django.conf import settings

from .base import PollResult, Provider, ProviderError, ProviderNotConfigured

API = os.environ.get('KA_LAMBDA_API_BASE', 'https://cloud.lambda.com/api/v1')  # cloud.lambda.ai is deprecated (OpenAPI v1.10.0)
GPU_MAP = {'nvidia-a100-40gb': 'gpu_1x_a100_sxm4', 'nvidia-a10g': 'gpu_1x_a10'}


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
        if not getattr(settings, 'KA_LAMBDA_BOOTSTRAP', False):
            raise ProviderNotConfigured('Lambda SSH bootstrap of the training container is not implemented yet')

    def _req(self, method, path, **kw):
        import requests

        r = requests.request(method, API + path, headers={'Authorization': f'Bearer {self._key()}'}, timeout=30, **kw)
        if r.status_code >= 400:
            raise ProviderError(f'Lambda API {method} {path}: {r.status_code} {r.text[:300]}')
        return r.json()

    def launch(self, job, job_dir):
        self.check_available()
        body = {'region_name': getattr(settings, 'KA_LAMBDA_REGION', 'us-east-1'),
                'instance_type_name': GPU_MAP.get(job.gpu_type, 'gpu_1x_a10'),
                'ssh_key_names': [getattr(settings, 'KA_LAMBDA_SSH_KEY', 'ka-orchestrator')],  # exactly one key
                'name': f'ka-job-{job.id}'}
        # Bootstrap would go in 'user_data' (plain-text cloud-init, <= 1 MB) - not implemented yet.
        data = self._req('POST', '/instance-operations/launch', json=body)
        ids = data.get('data', {}).get('instance_ids', [])
        if not ids:
            raise ProviderError('Lambda launch returned no instance id')
        return f'lambda:{ids[0]}'

    def poll(self, job):
        iid = job.provider_job_id.split(':', 1)[1]
        st = self._req('GET', f'/instances/{iid}').get('data', {}).get('status')
        if st in ('terminated', 'unhealthy'):
            return PollResult('exited', 1, f'instance {st}')
        return PollResult('running', detail=st or '')

    def cancel(self, job):
        self.cleanup(job)

    def cleanup(self, job):
        if job.provider_job_id.startswith('lambda:'):
            iid = job.provider_job_id.split(':', 1)[1]
            self._req('POST', '/instance-operations/terminate', json={'instance_ids': [iid]})
