"""Training worker: `python label_studio/manage.py ka_worker [--until-idle] [--interval 2]`."""

import logging
import signal
import time

from django.core.management.base import BaseCommand

from kentucky.orchestration import service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the Kentucky AI training orchestrator worker'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=2.0)
        parser.add_argument('--until-idle', action='store_true')

    def handle(self, *args, interval, until_idle, **kw):
        stop = {'v': False}
        signal.signal(signal.SIGTERM, lambda *a: stop.__setitem__('v', True))
        service.recover()
        self.stdout.write(f'ka_worker {service.WORKER_ID} started')
        if until_idle:
            service.run_until_idle(interval=interval)
            return
        while not stop['v']:
            try:
                service.tick()
            except Exception:  # noqa: BLE001
                logger.exception('worker tick failed')
            time.sleep(interval)
