"""Kentucky AI training container on Modal (operator-deployed; NOT deployed or tested yet).

Deploy (operator, Kentucky AI's own Modal workspace):
    modal deploy deploy/modal/ka_trainer.py

The orchestrator's ModalProvider spawns ``train_t4`` / ``train_a10g`` / ``train_a100`` / ``train_cpu`` with a
tarball of the job directory (spec.json + dataset bundle). The function runs the same entrypoint as the
local provider (``kentucky.training.runner``) and mirrors ``events.jsonl`` + ``artifacts/`` into the
``ka-training-runs`` Volume under /jobs/<job_id>/ so the orchestrator can stream progress.

Isolation: one container per job, no customer code, no database access, no secrets except the Volume.
"""

import modal

app = modal.App('ka-trainer')
volume = modal.Volume.from_name('ka-training-runs', create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version='3.12')
    # same versions as label_studio/kentucky/requirements.txt (verified locally); CUDA wheels from PyPI
    .pip_install('torch==2.15.0', 'torchvision==0.29.2', 'torch-geometric==2.8.1', 'transformers==5.23.0', 'numpy', 'pillow',
                 'opencv-python-headless==5.0.0.93', 'shapely==2.2.0')
    .add_local_python_source('kentucky', copy=True)  # only kentucky.training (Django-free) is imported in the container
)


def _run(job_id: int, bundle: bytes, max_runtime_s: int):
    from kentucky.training.modal_entry import run_job

    return run_job(job_id, bundle, max_runtime_s, volume_root='/runs', commit=volume.commit)


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
