"""Body of the Modal GPU function (deploy/modal/ka_trainer.py). Kept free of the Modal SDK so it is tested locally.

Unpacks the job bundle, runs ``kentucky.training.runner`` (identical on every provider) and mirrors
``events.jsonl`` + ``artifacts/`` into the volume under ``jobs/<job_id>/`` while it runs, so the orchestrator can
stream progress and collect the checkpoint.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path


def _mirror(job_dir: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    ev = job_dir / 'events.jsonl'
    if ev.exists():
        shutil.copyfile(ev, dst / 'events.jsonl')
    if (job_dir / 'artifacts').exists():
        shutil.copytree(job_dir / 'artifacts', dst / 'artifacts', dirs_exist_ok=True)


def run_job(job_id: int, bundle: bytes, max_runtime_s: int, volume_root: str, commit=lambda: None, interval: float = 10.0) -> dict:
    work = Path(tempfile.mkdtemp(prefix=f'ka-job-{job_id}-'))
    with tarfile.open(fileobj=io.BytesIO(bundle), mode='r:gz') as tf:
        tf.extractall(work, filter='data')
    job_dir = work / 'job'
    dst = Path(volume_root) / 'jobs' / str(job_id)
    stop = threading.Event()

    def loop():
        while not stop.wait(interval):
            _mirror(job_dir, dst)
            commit()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    root = str(Path(__file__).resolve().parents[2])
    env = {**os.environ, 'PYTHONPATH': root + os.pathsep + os.environ.get('PYTHONPATH', '')}
    try:
        p = subprocess.run([sys.executable, '-m', 'kentucky.training.runner', str(job_dir)], env=env, cwd=root,
                           timeout=float(max_runtime_s) + 120, check=False)
        code = p.returncode
    except subprocess.TimeoutExpired:
        code = 4
    stop.set()
    _mirror(job_dir, dst)
    commit()
    shutil.rmtree(work, ignore_errors=True)
    return {'exit_code': code}
