# Implementation status

Updated 2026-11-15. This is the resume point after any context loss: read this, `TEST_RESULTS.md`
and `ARCHITECTURE.md`, then run the test suite.

Legend: **Verified** = implemented and exercised by tests and/or a real end-to-end run here ·
**Untested on paid cloud** = implemented, verified locally, never run on a billable provider ·
**Partial** · **Blocked** · **Not implemented**.

## Definition of done (master prompt §25)

| # | Capability | Status | Where / evidence |
|---|---|---|---|
| 1 | Dataset management | Verified | Plan sets + plan set pages, `/api/ka/datasets`, `/api/ka/home/` |
| 2 | Vector blueprint ingestion (PDF, DXF) | Verified | `ingest/` — pdfplumber/pypdfium2, ezdxf; rotation-aware transforms; `test_coords_ingest.py` |
| 3 | Scanned blueprint ingestion | Verified | OpenCV LSD lines + RapidOCR text; Test A uses scans |
| 4 | CV segmentation labeling | Verified | Check screen (`review.js`) over the Label Studio annotation; precise outline editor = embedded LS engine (`?editor=1`) |
| 5 | GNN graph annotation | Verified | Graph Studio (`graph_studio.js`): primitives, groups, node labels, edge fixes, versions; Test B |
| 6 | Human annotation review | Verified | Keep/Dismiss/relabel/undo, Done approves the sheet; object review API; only approved labels train |
| 7 | Agent-assisted annotation | Verified | Geometry agent (graph rules) + model-in-the-loop proposals from the org's models, with provenance; Test D, `test_review_flow.py`. External LLM agents: not integrated (no service connected) |
| 8 | Dataset validation and versioning | Verified | Quality gates, immutable versions with content hash, group splits (no leakage), only checked sheets |
| 9 | CV dataset export | Verified | COCO, semantic masks, RLE; `test_dataset_export.py` |
| 10 | PyTorch Geometric export | Verified | `datasets/export.py`, graph JSON + PyG `.pt` |
| 11 | Commercially permissible model selection | Verified | `catalog.py` with per-checkpoint license fields; non-commercial checkpoints excluded; pretrained COCO marked "legal review pending — not deployable"; advanced Train dialog |
| 12 | Real segmentation training | Verified | LR-ASPP and Mask R-CNN on CPU; runs 7, 9, 11 in `TEST_RESULTS.md` |
| 13 | Real GNN training | Verified | GATv2/GraphSAGE/GCN node, GraphSAGE edge; runs 1–2 |
| 14 | Checkpoint creation | Verified | best + periodic checkpoints, sha256, resumable |
| 15 | Evaluation | Verified | held-out test split; IoU/Dice/boundary-F1/object counts, mask/box mAP, macro-F1; plain-English report card |
| 16 | Model registry | Verified | versions, lineage (start point, base version, data version), download if permitted, archive/restore |
| 17 | Functional inference endpoints | Verified | `POST /api/ka/v1/deployments/<slug>/predict` with API key — real curl call in `TEST_RESULTS.md` |
| 18 | Organization-scoped API access | Verified | API keys hashed, per org, rotate/revoke; Test E |
| 19 | Persistent job orchestration | Verified | DB state machine, `manage.py ka_worker`, heartbeats, cancel, timeouts, retries, crash recovery; Test F |
| 20 | Cloud GPU provider integration | **Untested on paid cloud** (Modal) / **Partial** (Lambda) | Modal adapter + app (`deploy/modal/ka_trainer.py`) — never run, no credentials; Lambda launch/terminate implemented, on-instance bootstrap not implemented so launching is refused. Both gated by `KA_ENABLE_PAID_COMPUTE` |
| 21 | Usage metering | Verified | idempotent ledger for training time, runs and API requests; dashboard on Billing |
| 22 | Billing-ready infrastructure | Verified locally / **Blocked** for live charges | monthly limit enforced before training, reservations for running jobs, payment-method gate; Stripe off until `KA_STRIPE_SECRET_KEY`; prices are placeholders |
| 23 | Organization isolation | Verified | org-prefixed storage, signed URLs, every query org-scoped; Test E + review scoping test |
| 24 | Kentucky AI-consistent UI | Verified | v5 design system, Light + Dark, all screens (see `DESIGN_TOKENS.md`) |
| 25 | Passing end-to-end tests | Verified | 40 passed (Tests A–F, review flow, training center) |

## Other prompt sections
* Training Center wizard (§13): dataset → readiness → task → architecture → starting point → recommended or
  advanced settings → cost estimate → authorize → live progress → evaluation → deploy. **Verified.**
* Experiment tracking (§15): Experiments page with lineage, metrics, runtime, hardware, compare (curves + config diff). **Verified.**
* Kentucky AI pretrained models: **Not available** — none exist in the audited repositories; the UI says so.
* Storage: local filesystem backend **Verified**; S3/R2 backend **Not implemented** (selected by `KA_STORAGE_BACKEND=s3` once written and credentialed).
* Dedicated hosting (always-on instances): **Not implemented**; deployments run in the platform process (serverless-style, metered per request).
* Hosted platform (Railway or similar): **Not deployed** — per instruction, no services connected yet.

## What needs credentials / paid verification
| Item | Needs |
|---|---|
| Modal GPU training | Modal workspace tokens, `KA_ENABLE_PAID_COMPUTE=1`, written OK from Modal for resale use (ToS §1.1/§1.3c) |
| Lambda GPU training | `LAMBDA_API_KEY`, region, SSH key, bootstrap implementation |
| Stripe | `KA_STRIPE_SECRET_KEY` (test mode first), real price table in `KA_PRICING` |
| Object storage | R2/S3 bucket + keys, S3 backend implementation |
| Production DB / hosting | Postgres, a host (Railway etc.), domain, TLS |

## Start the platform locally
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . && pip install -r label_studio/kentucky/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
export LABEL_STUDIO_BASE_DATA_DIR=$HOME/ka-data DJANGO_DB=sqlite
python label_studio/manage.py migrate
python label_studio/manage.py collectstatic --noinput
python label_studio/manage.py runserver 0.0.0.0:8080      # app at http://localhost:8080/ka/
python label_studio/manage.py ka_worker                   # second terminal: runs training jobs
cd label_studio && python -m pytest kentucky/tests -q     # 40 tests
```
The embedded labeling engine (precise outline editor) needs the Label Studio frontend build:
`cd web && bun install && bun --bun run vite build --config vite.config.editor.ts --base /ka/engine/`.
