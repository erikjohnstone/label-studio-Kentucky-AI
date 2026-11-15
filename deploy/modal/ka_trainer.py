"""Kentucky AI training container on Modal (operator-deployed; NOT deployed or tested yet).

Deploy (operator, Kentucky AI's own Modal workspace):
    modal deploy deploy/modal/ka_trainer.py

The orchestrator's ModalProvider spawns ``train_t4`` / ``train_a10g`` / ``train_a100`` / ``train_cpu`` with a
tarball of the job directory (spec.json + dataset bundle). The function runs the same entrypoint as the
local provider (``kentucky.training.runner``) and mirrors ``events.jsonl`` + ``artifacts/`` into the
``ka-training-runs`` Volume under /jobs/<job_id>/ so the orchestrator can stream progress.

Isolation: one container per job, no customer code, no database access, no secrets except the Volume.
"""

import io
import os
import subprocess
import sys
import tarfile
import threading
import time

import modal

app = modal.App('ka-trainer')
volume = modal.Volume.from_name('ka-training-runs', create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version='3.12')
    .pip_install('torch==2.5.1', 'torchvision==0.20.1', 'torch_geometric==2.6.1', 'transformers>=4.40', 'numpy', 'pillow',
                 'opencv-python-headless', 'shapely')
    .add_local_python_source('kentucky', copy=True)  # only the Django-free training package is used in the container
)


def _run(job_id: int, bundle: bytes, max_runtime_s: int):
    root = f'/runs/jobs/{job_id}'
    os.makedirs(root, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(bundle), mode='r:gz') as tf:
        tf.extractall('/tmp/job', filter='data')
    job_dir = '/tmp/job/job'
    stop = threading.Event()

    def mirror():
        while not stop.is_set():
            subprocess.run(['rsync', '-a', f'{job_dir}/events.jsonl', f'{job_dir}/artifacts', root + '/'], check=False)
            volume.commit()
            time.sleep(10)

    t = threading.Thread(target=mirror, daemon=True)
    t.start()
    p = subprocess.run([sys.executable, '-m', 'kentucky.training.runner', job_dir], timeout=max_runtime_s + 120, check=False)
    stop.set()
    subprocess.run(['rsync', '-a', f'{job_dir}/events.jsonl', f'{job_dir}/artifacts', root + '/'], check=False)
    volume.commit()
    return {'exit_code': p.returncode}


common = dict(image=image, volumes={'/runs': volume}, timeout=24 * 3600, retries=0)


@app.function(gpu='T4', **common)
def train_t4(job_id: int, bundle: bytes, max_runtime_s: int):
    return _run(job_id, bundle, max_runtime_s)


@app.function(gpu='A10G', **common)
def train_a10g(job_id: int, bundle: bytes, max_runtime_s: int):
    return _run(job_id, bundle, max_runtime_s)


@app.function(gpu='A100', **common)
def train_a100(job_id: int, bundle: bytes, max_runtime_s: int):
    return _run(job_id, bundle, max_runtime_s)


@app.function(cpu=4, **common)
def train_cpu(job_id: int, bundle: bytes, max_runtime_s: int):
    return _run(job_id, bundle, max_runtime_s)
