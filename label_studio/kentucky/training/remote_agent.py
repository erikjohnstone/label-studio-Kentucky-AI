"""Runs on a rented GPU instance (Lambda Cloud). Standard library + the training package only.

    python -m kentucky.training.remote_agent --bundle URL --events URL --artifacts URL --done URL \
        --max-runtime SECONDS --workdir /opt/ka

The instance gets nothing but presigned object URLs: it downloads the job bundle, runs the same entrypoint as every
other provider (``kentucky.training.runner``), streams ``events.jsonl`` back every few seconds, uploads the
artifacts, writes ``done.json`` with the exit code, and the instance then powers itself off. It never sees
platform credentials or the database.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path


def _http(method, url, data=None):
    try:
        import requests

        r = requests.request(method, url, data=data, timeout=120)
        r.raise_for_status()
        return r.content
    except ImportError:
        import urllib.request

        req = urllib.request.Request(url, data=data, method=method)
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - presigned https URL from the orchestrator
            return resp.read()


def run(bundle, events, artifacts, done, max_runtime, workdir, interval=10.0, code_root=None) -> int:
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(_http('GET', bundle)), mode='r:gz') as tf:
        tf.extractall(work, filter='data')
    job_dir = work / 'job'
    ev = job_dir / 'events.jsonl'
    stop = threading.Event()

    def push_events():
        if ev.exists():
            try:
                _http('PUT', events, ev.read_bytes())
            except Exception as e:  # noqa: BLE001 - keep training even if one upload fails
                print('events upload failed:', e, file=sys.stderr)

    def mirror():
        while not stop.wait(interval):
            push_events()

    t = threading.Thread(target=mirror, daemon=True)
    t.start()
    env = {**os.environ}
    root = code_root or str(Path(__file__).resolve().parents[2])
    env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
    try:
        p = subprocess.run([sys.executable, '-m', 'kentucky.training.runner', str(job_dir)], env=env, cwd=root,
                           timeout=float(max_runtime) + 120, check=False)
        code = p.returncode
    except subprocess.TimeoutExpired:
        code = 4
    stop.set()
    push_events()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        if (job_dir / 'artifacts').exists():
            tf.add(job_dir / 'artifacts', arcname='artifacts')
    _http('PUT', artifacts, buf.getvalue())
    _http('PUT', done, json.dumps({'exit_code': code, 'finished_at': time.time()}).encode())
    return code


def main(argv=None):
    a = argparse.ArgumentParser()
    for k in ('bundle', 'events', 'artifacts', 'done', 'workdir'):
        a.add_argument('--' + k, required=True)
    a.add_argument('--max-runtime', type=float, required=True)
    o = a.parse_args(argv)
    return run(o.bundle, o.events, o.artifacts, o.done, o.max_runtime, o.workdir)


if __name__ == '__main__':
    sys.exit(main())
