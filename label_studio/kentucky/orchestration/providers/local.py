"""Local development provider: runs the training container entrypoint as a child process (CPU)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from .base import PollResult, Provider

_PROCS: dict[int, subprocess.Popen] = {}
LS_ROOT = str(Path(__file__).resolve().parents[3])  # .../label_studio


class LocalProvider(Provider):
    name = 'local'
    paid = False

    def launch(self, job, job_dir):
        env = {**os.environ, 'PYTHONPATH': LS_ROOT + os.pathsep + os.environ.get('PYTHONPATH', ''),
               'KA_TORCH_THREADS': os.environ.get('KA_TORCH_THREADS', str(max(1, (os.cpu_count() or 2) - 1)))}
        log = open(Path(job_dir) / 'stdout.log', 'ab')
        p = subprocess.Popen([sys.executable, '-m', 'kentucky.training.runner', job_dir], cwd=LS_ROOT, env=env,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        _PROCS[p.pid] = p
        return f'pid:{p.pid}'

    def _pid(self, job):
        try:
            return int(job.provider_job_id.split(':', 1)[1])
        except (IndexError, ValueError):
            return None

    def poll(self, job):
        pid = self._pid(job)
        if pid is None:
            return PollResult('lost', detail='no pid')
        p = _PROCS.get(pid)
        if p is not None:
            rc = p.poll()
            if rc is None:
                return PollResult('running')
            _PROCS.pop(pid, None)
            return PollResult('exited', rc)
        # Adopted after a worker restart: we can't reap, only check liveness. A zombie (dead, not yet reaped) is gone.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return PollResult('exited', None, 'process gone (adopted)')
        except PermissionError:
            return PollResult('running')
        try:
            with open(f'/proc/{pid}/status') as f:
                if any(line.startswith('State:') and 'Z' in line.split()[1] for line in f):
                    try:
                        os.waitpid(pid, os.WNOHANG)  # reap it if it is ours
                    except ChildProcessError:
                        pass
                    return PollResult('exited', None, 'process gone (adopted)')
        except FileNotFoundError:
            return PollResult('exited', None, 'process gone (adopted)')
        except OSError:
            pass
        return PollResult('running')

    def cancel(self, job):
        Path(job.job_dir, 'CANCEL').touch()

    def kill(self, job):
        pid = self._pid(job)
        if pid is None:
            return
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        p = _PROCS.pop(pid, None)
        if p is not None:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def cleanup(self, job):
        self.kill(job)
