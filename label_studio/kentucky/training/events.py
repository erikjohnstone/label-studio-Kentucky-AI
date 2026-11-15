"""Training event stream (JSONL). Workers on any provider write the same events; the orchestrator tails them."""

from __future__ import annotations

import json
import os
import time


class Reporter:
    def __init__(self, path: str):
        self.path = path
        self.t0 = time.time()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def emit(self, type_: str, **data):
        rec = {'type': type_, 't': round(time.time() - self.t0, 3), 'ts': time.time(), **data}
        with open(self.path, 'a') as f:
            f.write(json.dumps(rec, default=float) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def status(self, s: str, **kw):
        self.emit('status', status=s, **kw)

    def log(self, msg: str):
        self.emit('log', message=msg)

    def metric(self, **kw):
        self.emit('metric', **kw)

    def heartbeat(self):
        """Called every training step: also where Stop is honoured, so it takes seconds, not a whole round."""
        self.emit('heartbeat')
        check_cancel(os.path.dirname(self.path))


class Cancelled(Exception):
    pass


def check_cancel(job_dir: str):
    if os.path.exists(os.path.join(job_dir, 'CANCEL')):
        raise Cancelled()
