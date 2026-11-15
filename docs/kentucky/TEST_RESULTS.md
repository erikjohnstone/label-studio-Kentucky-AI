# Test results

Measured on the development container (4 vCPU, no GPU, Python 3.12.3, torch 2.15 CPU, torch_geometric 2.8),
2026-11-15. Every number below was produced by the code in this repository; nothing is estimated.

## Automated suite

```bash
cd label_studio
python -m pytest kentucky/tests -q -p no:cacheprovider
# 60 passed
```

| File | What it proves |
|---|---|
| `test_coords_ingest.py` | PDF (0/90/180/270° rotation) source↔image transforms round-trip and align with the render; extracted primitives land on the source geometry; DXF and scan extraction; tile and LS-percent round-trips; unsafe/unsupported uploads are rejected |
| `test_dataset_export.py` | RLE round-trip; COCO / semantic masks / graph JSON / PyG export round-trip; unreviewed and rejected labels never become ground truth; group splits never leak a building across train/val/test; quality gates flag invalid and duplicate geometry |
| `test_e2e.py` | **Test A** CV segmentation on scanned drawings (upload → label → review → export masks → real training → checkpoint → evaluation → registry → inference → predictions over the drawing). **Test B + C** vector GNN (PDF/DXF → primitives → graph → node labels/edge fixes/groups → validate → PyG export → real GNN training → evaluation → registry → inference) and fine-tuning from the registered checkpoint compared with the baseline. **Test D** agentic annotation with provenance (proposals → accept/modify/reject → provenance saved → export contains only approved; rejected never ground truth) |
| `test_review_flow.py` | Check screen: AI suggestions → Keep / relabel / Dismiss / undo → autosaved Label Studio annotation keeps agent provenance (`ka<proposal>` ids) → Done dismisses the rest and approves the sheet; home overview states; only checked sheets enter a dataset version; org scoping of every review endpoint; outline repair of self-crossing polygons |
| `test_training_center.py` | Training Center advanced mode: defaults + schema, per-architecture estimates, explicit architecture / start point / settings stored exactly, invalid settings rejected, run lineage for Experiments |
| `test_storage_s3.py` | S3-compatible backend (R2/S3/MinIO) against moto's emulated S3: round-trips, org-prefix refusal, prefix delete, PDF ingestion writing to the bucket, sheet image + signed download served from it, cross-org 404 |
| `test_hosting.py` | Always-on hosting: hourly accrual is idempotent, pro-rata on pause, nothing accrues while paused, no back-billing on resume; auto-pause at the spend limit; dedicated deploy refused when it would pass the limit |
| `test_lambda_provider.py` | Lambda Cloud: launch through a fake Lambda API records instance type, SSH key and a cloud-init script with no secrets; the script's agent runs locally against emulated S3 (presigned URLs only) and performs real GNN training; the orchestrator syncs events + checkpoint, registers the model, bills once and terminates the instance; a lost instance fails and is terminated; refuses without bucket or SSH key |
| `test_modal_provider.py` | Modal: stand-in SDK whose `spawn` runs the real deployed function body (`training/modal_entry.py`) into a local volume; real training, progress mirrored, checkpoint synced, model registered, billed once, call cancelled on cleanup |
| `test_stripe.py` | Stripe test mode with the HTTP API mocked: customer created once (idempotent), `pm_card_visa` attached as default, one invoice item per ledger charge keyed by the ledger idempotency key, sub-cent amounts as decimal cents; live keys blocked without the operator flag |
| `test_base_models.py` | DINOv2-S segmentation and RT-DETRv2 detection train through the job pipeline, register and serve predictions; their catalog records carry Apache-2.0 licenses pinned to exact revisions |
| `test_outline_choice.py` | One-click outline training picks DINOv2-S only for mostly-scanned sets with 5+ checked sheets, LR-ASPP otherwise, and keeps the best-scoring architecture already trained on the set (a newer, worse experiment does not take over) |
| `test_estimates.py` | Train-screen time estimates bracket 6 measured benchmark runtimes; the runtime limit scales with the job (1–24 h) and the estimate uses the same settings the job will |
| `test_security.py` | **Test E** org B cannot read or change org A's drawings, datasets, annotations, jobs, checkpoints, models, deployments or API keys (API + signed file URLs) |
| `test_training_failures.py` | **Test F** invalid datasets/selections fail validation; missing weights / unknown init / CPU-only restrictions; paid providers require operator enablement + payment method; cancellation kills the worker and bills once; timeouts terminate hung workers; worker crash retried (infra failure not charged); training-code errors fail without retry; ledger idempotency |

## End-to-end runs through the browser (Playwright, real UI, real server + worker)

Scripts are in the session scratchpad; the steps and results:

1. **Upload** four synthetic vector PDFs through the Plan sets drop zone → plan set "Office building — Level 2"
   created, 4 sheets ingested (vector primitives, text, tiles).
2. **Find more with AI** on a sheet the org's models had never seen: the newest instance model
   (Mask R-CNN MobileNetV3, trained on a different plan set) proposed 31 items.
3. **Keep / Dismiss** with the K / D keys; drew one door with the Door tool. Server afterwards held exactly
   5 regions in the Label Studio annotation (4 kept + 1 drawn), with agent provenance on the kept ones.
4. **Done · Next sheet** approved the sheet and opened the next one; repeated until 4 of 5 sheets were checked.
5. **Train** (recommended): the readiness check blocked training when 7 kept outlines were self-crossing
   (mask tracing artefact). Fixed at the source (outline repair) — then training ran.
6. **Training live** page showed the real rounds and the check-sheet metric after each round.
7. **Results** for run 11 (LR-ASPP, fine-tuned from the org's v4, 30 epochs, 123 s CPU): on the held-out
   sheet it found **8 of 8 doors** and **38 of 39 walls**; mean IoU 0.395.
8. **Deploy** from the results page → endpoint created. **API key** created on the API keys page.
9. **Real HTTP call** with the key (curl, base64 PNG of an unseen sheet): `200`, 14 predictions
   (9 walls, 5 doors), 596 ms, metered `$0.002`. Same call without a key: `401`.
10. **Try it** on the Deployments page with another plan image: 26 walls / 17 doors drawn over the image.

A data bug found by this run and fixed: dataset versions used to include sheets nobody had checked, which
taught the model "no walls here" and could make the test sheet empty. Versions now contain only checked
sheets (covered by `test_review_flow.py`).

## Measured training runs (this database)

| Run | Data | Architecture | Start | Epochs | CPU time | Held-out result |
|---|---|---|---|---|---|---|
| 1 | Synthetic office plans v1 | GATv2 node classifier | scratch | 60 | 6 s | macro-F1 0.91 (val) — windows 24/24, walls 126/128, doors 8/14 |
| 2 | Synthetic office plans v1 | GraphSAGE relation | scratch | 60 | 6 s | macro-F1 0.687 (val) |
| 3, 5 | Synthetic office plans v1 | LR-ASPP | scratch | 6 / 25 | 31 / 48 s | 0 IoU — before the class-weighting + BN-recalibration fixes |
| 4, 6, 8 | Synthetic office plans v1 | Mask R-CNN MBv3 | scratch | 4–14 | 95–657 s | 0 mAP — before the resize / GroupNorm / AdamW fixes |
| 7 | Synthetic office plans v1 | LR-ASPP | scratch | 25 | 215 s | mean IoU 0.448 (test) — doors 12/12, windows 10/10, walls 42/46 |
| 9 | Synthetic office plans v1 | Mask R-CNN MBv3 | scratch | 16 | 1034 s | mask mAP50 0.176 (test) — walls 27/46, doors 6/12 |
| 10 | Office building — Level 2 v1 | LR-ASPP | your v3 | 30 | 71 s | test sheet unlabeled (bug above); val: walls 16/16, doors 2/2 |
| 11 | Office building — Level 2 v2 | LR-ASPP | your v4 | 30 | 123 s | mean IoU 0.395 (test) — doors 8/8, walls 38/39 |

"Found" counts are object-level (a labeled item counts as found when the prediction covers it), computed
by `training/metrics.py`; IoU/mAP are pixel/mask metrics on the same held-out sheet. These are synthetic
drawings — production accuracy must be measured on customer plans.

## Not verified here

* Paid GPUs (Modal, Lambda): both verified end to end against stand-ins (see above); no billable GPU was created.
* Stripe: verified against a mocked Stripe API in test mode; never called the real API (no key).
* Postgres and a real R2/S3 bucket in production (S3 code path verified only against moto); Railway/hosted deployment.

## Production build and PostgreSQL (no hosting service connected)
* **PostgreSQL 16** (local): all migrations apply; the full suite passes on Postgres (`50 passed in 317 s`, connection vendor `postgresql`).
* **Image**: `Dockerfile.kentucky` built successfully (4.3 GB). In this sandbox the build needed the sandbox's TLS proxy CA
  and an HTTPS Debian mirror injected into a throwaway copy of the Dockerfile; the committed file is unchanged and needs
  neither on a normal builder.
* **Containers**: web (`start-web.sh`, gunicorn) and worker (`start-worker.sh`) from the image, on Postgres, sharing a
  data volume. `/health/` 200, `/ka/` 302 → login, static 200, labeling engine 200. Browser run against it: 3 PDFs uploaded
  → AI mark-up on each sheet (geometry agent; no model yet) → 151 items kept and approved → training ran in the worker
  container (LR-ASPP, completed in ~3 min) → results page "Model v1 finds 10 of every 10 doors" on its held-out sheet →
  deployed → API key → authenticated predict on an unseen sheet: 200, 74 items, 782 ms, metered $0.002.
* Lesson recorded in DEPLOYMENT.md: separate web and worker services need shared storage (S3/R2 backend or a volume).

Two production bugs found by these tests and fixed: job specs used absolute paths from the orchestrator machine
(would break every remote provider) — now relative to the job directory; newer botocore's default streaming
checksums corrupted uploads to S3-compatible stores (also an R2 incompatibility) — checksums now only when required.

## Base model comparison (same data snapshot, same held-out test sheet, CPU)
"Office building — Level 2", dataset version 3 (2 training sheets, 1 check sheet, 1 test sheet).

| Run | Model | Start | Test result | Walls found | Doors found | CPU time |
|---|---|---|---|---|---|---|
| 13 | LR-ASPP MobileNetV3 | from zero | mean IoU 0.336 | 39/39 | 8/8 | 165 s |
| 12 | DINOv2-S, first head | pretrained (Apache-2.0) | mean IoU 0.071 | 1/39 | 0/8 | 343 s |
| 16 | DINOv2-S, multi-scale head | pretrained (Apache-2.0) | mean IoU 0.105 | 34/39 | 0/8 | 580 s |
| 14 | Mask R-CNN MobileNetV3 | from zero | mask mAP50 0.165 | 25/39 | 0/8 | 402 s |
| 17 | RT-DETRv2-R18 | pretrained (Apache-2.0) | mAP50 0.432 | 9/39 | 8/8 | 453 s |

Conclusions on this (small, synthetic) data: RT-DETRv2 is the better item model for doors/symbols; long walls
are better as outline areas. DINOv2 did not beat LR-ASPP and is marked experimental. Run 15 (RT-DETRv2) trained
fine but its long-running worker predated the new catalog entry and could not register it; the worker now
fails with an explicit "restart the worker" message and the deploy rule is documented.

## Benchmarks on larger plan sets (all through the platform UI)
Plan sets uploaded through the Plan sets drop zone; exact labels from the drawing generator (scan labels follow the
scan skew, verified to 0.1 px); every run started from Train → Customize; same snapshot and held-out test sheet per table.

**Scanned plans** — 10 skewed, noisy scans (8 train / 1 check / 1 test sheet), 503 labeled items.

| Model | Start | Test result | Walls | Doors | Windows | CPU time |
|---|---|---|---|---|---|---|
| **DINOv2-S segmentation** | your DINOv2 v1 (one-click Train) | **mean IoU 0.767** | 47/47 | 12/12 | 11/11 | 41 min |
| DINOv2-S segmentation | pretrained (Apache-2.0) | mean IoU 0.744 | 47/47 | 12/12 | 11/11 | 39 min |
| LR-ASPP MobileNetV3 | from zero | mean IoU 0.627 | 47/47 | 12/12 | 11/11 | 10 min |
| **D-FINE-S** | pretrained (Apache-2.0) | **mAP50 0.954** | 45/47 | 12/12 | 11/11 | 13 min |
| **RF-DETR-S** (after the backbone-rate fix) | pretrained (Apache-2.0) | **mAP50 0.981** | 45/47 | 12/12 | 11/11 | 30 min |
| D-FINE-S | your vector-plan model (fine-tuned) | mAP50 0.963 | 46/47 | 12/12 | 11/11 | 8 min |
| RT-DETRv2-R18 | pretrained (Apache-2.0) | mAP50 0.753 | 30/47 | 12/12 | 8/11 | 18 min |
| Mask R-CNN MobileNetV3 | from zero | mAP50 0.615 | 36/47 | 12/12 | 4/11 | 37 min |

**Vector plans** — 10 PDFs (3 rotated 90°) + 3 DXF (9 train / 2 check / 2 test sheets), 830 labeled items, 3,154 labeled lines.

| Model | Start | Test result | Walls | Doors | Windows | CPU time |
|---|---|---|---|---|---|---|
| LR-ASPP MobileNetV3 | from zero | mean IoU 0.665 | 118/118 | 34/34 | 14/22 | 6 min |
| DINOv2-S segmentation | pretrained (Apache-2.0) | mean IoU 0.651 | 118/118 | 34/34 | 12/22 | 53 min |
| **RT-DETRv2-R18** | pretrained | **mAP50 0.893** | 101/118 | 34/34 | 22/22 | 27 min |
| D-FINE-S | pretrained | mAP50 0.785 | 93/118 | 32/34 | 21/22 | 20 min |
| **Graph transformer (GPS + GINE)** | from zero | **macro-F1 1.000** | 472/472 lines | 68/68 | 66/66 | 12 s |
| GATv2 | from zero | macro-F1 0.992 | 468/472 | 68/68 | 66/66 | 8 s |
| GCN | from zero | macro-F1 0.992 | 468/472 | 68/68 | 66/66 | 6 s |
| GraphSAGE | from zero | macro-F1 0.986 | 467/472 | 67/68 | 66/66 | 6 s |
| GraphSAGE connections | from zero | macro-F1 0.927 | — | — | — | 16 s |

What changed in the product because of these numbers: D-FINE-S is the default item model for scanned plan sets and
RT-DETRv2 for vector sets; DINOv2-S is the default outline model for scanned sets with 5+ checked sheets (it trailed with 2 training sheets, led
with 8 scans, and tied LR-ASPP on clean vector drawings at 9x the time — check score 0.82 but test 0.65);
the graph transformer is the default line-by-line model; Find more with AI takes each item type from the model with
the best measured score for it. Synthetic drawings are easier than real ones — graph models reaching 1.00 here does
not mean they will on customer CAD.

**Find more like this** (mark one symbol, template search): tuned on 12 searches over scans and vectors — 83% of repeats
found, 0 wrong; through the Check screen on an unseen scan: 11/11 other doors, 0 wrong.

**Bugs found by running these through the platform, all fixed:** a stale worker could not register new models (now an
explicit message + deploy rule); numpy types in proposal evidence broke saving; skewed-scan ground truth ignored the
skew (test data); Deployments listed oldest first; finished jobs never freed their working copies (11.4 GB here) and a
full disk produced a cryptic, charged, non-retried failure. Later round: one-click Train always used LR-ASPP (now
picks by measurement: DINOv2-S for scanned sets with 5+ checked sheets, else LR-ASPP, or the best-scoring
architecture already trained on the set); it continued from the newest model anywhere in the org instead of this
plan set's own; time estimates were 1.5-10x high (now calibrated on 18 real runs, test pins them) and assumed 12
crops per sheet that jobs never used; every job had a fixed 1 h limit although a 9-sheet DINOv2 run takes 53 min
(the limit now scales with the job, 1-24 h); "How it's improving" showed "v1 → v1" for two architectures. Continuing a
trained DINOv2 at the full learning rate dropped its check score from 0.72 to 0.45 in one epoch (it recovered to
0.735 and a better test score, 0.767, but only by luck of a long run): continuing now scores the starting model
first and keeps it unless training beats it, at 0.3x the learning rate.

**Transfer between plan types:** D-FINE-S fine-tuned on the scans from the model trained on vector plans reached
mAP50 0.963 in 8 min, better and faster than starting from the public COCO weights (0.954, 13 min) — a model
trained on one plan set is a good starting point for the next, even across scan/vector.


## Research-driven changes (Nov 15, later) — all through the platform
After a 7-track literature and license review (research/MODEL_REVIEW_2026-11.md):
* **Lineup:** recommended defaults (DINOv2-S areas, D-FINE-S items, GPS lines); RF-DETR-S and GATv2 shown; older models
  under "Other models"; SegFormer, Mask R-CNN MobileNet, GCN retired from new training. Checked in the Train dialog.
* **Bug: one-click Train started from zero** when no earlier model existed, even for models with a licensed
  pretrained start. Now uses the pretrained start.
* **Tiled detection:** sheets larger than ~1.25 crops are detected tile by tile and merged. Test: 64 symbols incl.
  ones cut by tile edges (and by two edges at once) found exactly once; a detector capped at 25 per pass finds all 64
  with tiles; a stray oversized box does not swallow real symbols. Two merge bugs found and fixed by those tests.
* **Layer + line style features:** PDF dash patterns and DXF linetypes (BYLAYER resolved) are extracted; layer
  discipline (A/M/P/E...) and name words feed the line-by-line models. An existing GPS model still predicts via the API.
* **Takeoff:** run lengths per system (ft), double-line centerlines, elbows/tees/crosses, scale from the sheet's scale
  note or CAD units. Wall takeoff vs drawing truth on 5 plans: 0.15%, 0.00%, 0.73%, 0.57%, 0.80% error. End-cap
  pairing bug found by the truth test and fixed.
* **Bug: a killed training machine discovered after its time limit was marked 'timed out'** (charged, not retried)
  — happened to a DINOv2 run here when memory ran out. Now retried as an infrastructure failure, not charged.
* **RF-DETR fixed:** it was not learning to place boxes (check mAP50 0.001 after 8 rounds) because its DINOv2 backbone
  trained at the full rate; the detector warm-up also reset every parameter group to one rate. Backbone at 0.15x
  (RF-DETR's recipe), per-group warm-up, batch 2 at its native 512 px: 0.781 after 4 rounds, memory 7 GB -> 3.9 GB;
  test mAP50 0.981 on the scan benchmark (vs 0.954 / 0.963 for D-FINE-S), so it is now the recommended item counter.
