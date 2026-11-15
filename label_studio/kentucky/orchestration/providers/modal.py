"""Modal adapter (selected initial production GPU path). NOT exercised against real Modal yet.

Deployment model: an operator deploys ``deploy/modal/ka_trainer.py`` (one Modal App with a GPU
function that runs ``kentucky.training.runner``) under Kentucky AI's Modal workspace. Customers never
need a Modal account. This adapter spawns that function with the job bundle, polls the FunctionCall,
and copies events/artifacts back from a Modal Volume.

Requires: ``pip install modal``, ``MODAL_TOKEN_ID`` / ``MODAL_TOKEN_SECRET``, ``KA_MODAL_APP`` (default
``ka-trainer``), and ``KA_ENABLE_PAID_COMPUTE=1``.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

from django.conf import settings

from .base import PollResult, Provider, ProviderError, ProviderNotConfigured

GPU_MAP = {'nvidia-t4': 'T4', 'nvidia-a10g': 'A10G', 'nvidia-a100-40gb': 'A100', 'cpu-4': None}


class ModalProvider(Provider):
    name = 'modal'
    paid = True

    def _modal(self):
        try:
            import modal  # noqa: F401
        except ImportError:
            raise ProviderNotConfigured('modal SDK not installed (pip install modal)')
        if not (os.environ.get('MODAL_TOKEN_ID') and os.environ.get('MODAL_TOKEN_SECRET')):
            raise ProviderNotConfigured('MODAL_TOKEN_ID / MODAL_TOKEN_SECRET not configured')
        import modal

        return modal

    def check_available(self):
        self._modal()

    def _fn(self, job):
        modal = self._modal()
        app = getattr(settings, 'KA_MODAL_APP', 'ka-trainer')
        gpu = GPU_MAP.get(job.gpu_type, 'T4')
        name = f'train_{(gpu or "cpu").lower()}'
        return modal, modal.Function.from_name(app, name)

    def launch(self, job, job_dir):
        modal, fn = self._fn(job)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tf:
            tf.add(job_dir, arcname='job')
        try:
            call = fn.spawn(job_id=job.id, bundle=buf.getvalue(), max_runtime_s=job.max_runtime_s)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f'Modal spawn failed: {e}')
        return f'modal:{call.object_id}'

    def _call(self, job):
        modal = self._modal()
        return modal.FunctionCall.from_id(job.provider_job_id.split(':', 1)[1])

    def poll(self, job):
        call = self._call(job)
        try:
            result = call.get(timeout=0)
        except TimeoutError:
            return PollResult('running')
        except Exception as e:  # noqa: BLE001
            return PollResult('exited', 1, f'modal error: {e}')
        self._result = result
        return PollResult('exited', int(result.get('exit_code', 1)) if isinstance(result, dict) else 1)

    def sync(self, job, job_dir):
        modal = self._modal()
        vol = modal.Volume.from_name(getattr(settings, 'KA_MODAL_VOLUME', 'ka-training-runs'))
        prefix = f'/jobs/{job.id}'
        for entry in vol.listdir(prefix, recursive=True):
            if entry.type.name != 'FILE':
                continue
            rel = entry.path[len(prefix):].lstrip('/')
            dst = Path(job_dir) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, 'wb') as f:
                for chunk in vol.read_file(entry.path):
                    f.write(chunk)

    def cancel(self, job):
        try:
            self._call(job).cancel()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f'Modal cancel failed: {e}')

    def cleanup(self, job):
        # Modal functions are serverless: cancelling the call releases the GPU container.
        if job.provider_job_id.startswith('modal:'):
            try:
                self._call(job).cancel()
            except Exception:  # noqa: BLE001
                pass
