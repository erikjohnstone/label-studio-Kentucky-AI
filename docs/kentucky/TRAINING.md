# Training

## Wizard (`/ka/training/`)
1 dataset → 2 readiness (from the immutable version) → 3 task (only tasks the version is ready for) →
4 architecture (advisor recommendation shown) → 5 starting checkpoint (scratch / open checkpoint with
license status / your registered version) → 6 recommended or advanced config (every field validated
server-side) → 7 estimate (runtime range, customer cost range, max at runtime limit) → 8 explicit
authorization (checkbox + max spend) → 9 live monitoring (`/ka/experiments/<id>/`) → 10 evaluation and
**Review & deploy**.

## Pipelines (all real; `kentucky/training/`)

| Track | Data | Loss / metrics |
|---|---|---|
| Semantic seg (`cv.train_semantic`) | sheet renders scaled by `training_scale`; random crops biased to foreground from **train sheets only**; flips, 90° rotations, brightness, scan noise | class-weighted CE (absent classes weight 0); IoU, mIoU, Dice, precision, recall, pixel acc, boundary F1, per-class object count error and missing-object rate, mIoU by vector vs raster sheets |
| Instance seg (`cv.train_instance`) | COCO polygons/RLE → boxes + masks, crops | Mask R-CNN losses; mask AP@50 / AP@75 per class, precision/recall/TP/FP/FN, count error |
| GNN node / edge (`gnn.train_gnn`) | PyG graphs (x, edge_index, edge_attr), batched with PyG DataLoader | CE with ignore_index for unverified targets; accuracy, macro/micro F1, per-class P/R/F1, confusion matrix; edge models add graph consistency (components of predicted `same_object` edges that merge different GT classes) |

Precise-BN: models with BatchNorm trained from scratch get their running statistics recomputed on
training crops before every evaluation and before the checkpoint is saved; the Mask R-CNN MobileNet
backbone uses GroupNorm. (Without this, eval-mode outputs collapse to background — found and fixed
during testing.)

Recommended defaults per template: `training/config.py` (lr, optimizer, batch, epochs, scheduler,
augmentation, early stopping, checkpoint frequency, validation interval, seed, max runtime). Advanced
overrides are type/range checked; unknown keys are rejected. The fully resolved config, seed, code
version (git SHA) and dataset version are stored on the job.

## Job lifecycle
`CREATED → VALIDATING → CREATED (awaiting authorization) → QUEUED → PROVISIONING → PREPARING → TRAINING →
EVALUATING → SAVING → COMPLETED`, or `FAILED / CANCELLED / TIMED_OUT`. Every transition is appended to
`status_history` with a reason.

* **Queue / concurrency**: optimistic claim (`QUEUED → PROVISIONING`), `KA_MAX_CONCURRENT_JOBS` (2) and
  `KA_MAX_CONCURRENT_JOBS_PER_ORG` (1).
* **Heartbeats**: runner emits events; no heartbeat for `KA_HEARTBEAT_STALE_S` (600 s) → kill + retry.
* **Cancel**: `CANCEL` file → runner stops at the next check; force-kill after 20 s.
* **Runtime limit**: runner deadline + orchestrator kill at `max_runtime_s + KA_RUNTIME_GRACE_S`.
* **Retries**: only infrastructure failures (process vanished, provider error, stale heartbeat), up to
  `max_attempts` (2). Training-code errors (bad data, missing weights, NaNs) fail without retry.
* **Crash recovery**: on worker start `recover()` adopts live processes and requeues/fails lost ones.
* **Cleanup**: `provider.cleanup()` runs on every terminal path (kills the process group / cancels the
  Modal call / terminates the Lambda instance).
* **Registration**: artifact SHA-256 verified against the runner's event, copied to org storage, new
  `ModelVersion` with metrics, label map, I/O schema and license record.

## Commands
```bash
python label_studio/manage.py ka_worker                # long-running worker
python label_studio/manage.py ka_worker --until-idle   # drain the queue and exit
python -m kentucky.training.runner <job_dir>           # what every provider executes (cwd: label_studio/)
```

## Local CPU fallback
The `cpu-local` tier runs real training on CPU with the synthetic plan generator
(`kentucky/samples/synthetic.py`) or your data. See `TEST_RESULTS.md` for measured runs.
