"""Compute provider abstraction.

A provider runs ``kentucky.training.runner`` against a job directory that contains ``spec.json``
and the dataset bundle, and makes ``events.jsonl`` + ``artifacts/`` available locally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from django.conf import settings


class ProviderError(Exception):
    """Provider-side failure (retry may be safe)."""


class ProviderNotConfigured(ProviderError):
    pass


class PaidComputeNotAuthorized(ProviderError):
    pass


@dataclass
class PollResult:
    state: str  # running | exited | lost
    exit_code: int | None = None
    detail: str = ''


class Provider:
    name = 'base'
    paid = False

    def check_available(self):
        """Raise ProviderNotConfigured if credentials / SDK are missing."""

    def launch(self, job, job_dir: str) -> str:
        raise NotImplementedError

    def poll(self, job) -> PollResult:
        raise NotImplementedError

    def sync(self, job, job_dir: str):
        """Bring remote events/artifacts into job_dir (no-op for local)."""

    def cancel(self, job):
        raise NotImplementedError

    def cleanup(self, job):
        """Terminate/release ALL paid resources for the job. Must be idempotent and safe to call twice."""


def paid_compute_enabled() -> bool:
    return bool(getattr(settings, 'KA_ENABLE_PAID_COMPUTE', False)) or os.environ.get('KA_ENABLE_PAID_COMPUTE') == '1'


def get_provider(name: str) -> Provider:
    from .lambda_cloud import LambdaProvider
    from .local import LocalProvider
    from .modal import ModalProvider

    providers = {'local': LocalProvider, 'modal': ModalProvider, 'lambda': LambdaProvider}
    if name not in providers:
        raise ProviderNotConfigured(f'Unknown provider {name}')
    p = providers[name]()
    if p.paid and not paid_compute_enabled():
        raise PaidComputeNotAuthorized(
            f'Provider {name} launches paid GPU resources; it is disabled until KA_ENABLE_PAID_COMPUTE=1 is set by an operator.'
        )
    return p
