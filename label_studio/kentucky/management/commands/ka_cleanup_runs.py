"""Free disk used by finished training jobs (dataset copies and checkpoints; the registered models stay in storage)."""

from django.core.management.base import BaseCommand

from kentucky.models import TERMINAL_STATES, TrainingJob
from kentucky.orchestration.service import cleanup_job_dir


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **kw):
        total, n = 0, 0
        for job in TrainingJob.objects.filter(status__in=TERMINAL_STATES).exclude(job_dir=''):
            freed = cleanup_job_dir(job)
            total += freed
            n += bool(freed)
        self.stdout.write(f'cleaned {n} job folders, freed {total / 1e9:.2f} GB')
