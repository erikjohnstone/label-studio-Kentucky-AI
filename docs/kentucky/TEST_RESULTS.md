# Test results

Measured on the development container (4 vCPU, no GPU, Python 3.12.3, torch 2.15 CPU, torch_geometric 2.8),
2026-11-15. Every number below was produced by the code in this repository; nothing is estimated.

## Automated suite

```bash
cd label_studio
python -m pytest kentucky/tests -q -p no:cacheprovider
# 44 passed
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

* Paid GPUs (Modal, Lambda): adapters implemented and unit-tested with fakes; no billable GPU was created.
* Stripe: off unless `KA_STRIPE_SECRET_KEY` is set; ledger and limits are tested locally.
* Postgres and a real R2/S3 bucket in production (S3 code path verified only against moto); Railway/hosted deployment.
