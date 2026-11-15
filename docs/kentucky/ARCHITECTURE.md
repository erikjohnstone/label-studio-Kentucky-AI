# Kentucky AI Platform — Architecture

The platform extends this Label Studio fork with one Django app, `label_studio/kentucky/`, plus a
Django-free training package that runs identically on a laptop CPU or a cloud GPU container.
Upstream Label Studio code is touched in only four places: the app registration (`INSTALLED_APPS`),
the URL include (`core/urls.py`), and three privacy defaults (third-party Sentry DSNs, analytics and
the PyPI version check are now **off** by default). Upstream merges stay practical.

```
Upload ─▶ Prepare ─▶ Label ─▶ Review ─▶ Version ─▶ Select model ─▶ Train ─▶ Evaluate ─▶ Deploy ─▶ API ─▶ Improve
  │          │         │         │          │            │            │          │          │        │        │
ingest/   graph/    LS editor  datasets/  datasets/    catalog.py   orchestration/ training/ registry  api.py   agent/ (model-
pipeline  builder   + Graph    quality    versioning   + training/  service +     metrics   (models)  predict  in-the-loop
          + agent   Studio     + review   + export     config       providers                         + keys    proposals)
```

## Components

| Area | Code | Notes |
|---|---|---|
| Data model (canonical schema) | `kentucky/models.py` | Org-scoped rows: Dataset, Taxonomy (versioned), SourceDocument, Sheet, CanonicalObject, SheetGraph (versioned), Proposal, DatasetVersion, TrainingJob, RegisteredModel, ModelVersion, Deployment, ApiKey, BillingAccount, LedgerEntry, AuditLog |
| Coordinates | `kentucky/coords.py` | One affine `source → image` per sheet; tile, LS-percent, training and prediction spaces derive from it. Round-trip tested. |
| Ingestion | `kentucky/ingest/` | Magic-byte validation and active-content rejection → private storage → per-page extraction (pdfplumber/pdfium vectors + text; ezdxf entities/layers/blocks; OpenCV LSD vectorization + RapidOCR for scans) → PNG render + 512 px tile pyramid → Sheet + Label Studio task |
| Graph | `kentucky/graph/builder.py` | Candidate graph from primitives (touch / intersect / parallel-near / near-text); versioned feature spec shared by export and inference; topology + label validation |
| CV labeling | Label Studio editor (`labeling.py`) | Each dataset owns one LS project; each sheet is one LS task. Polygon / box / brush / keypoint results sync into CanonicalObjects. Agent proposals are LS *predictions*. |
| Graph labeling | Graph Studio (`static/kentucky/graph_studio.js`) | SVG blueprint + primitives, bidirectional selection with an object-level graph view, labels / groups / edges / semantic nodes, proposals, validation, versioned saves, review, model comparison |
| Agents | `kentucky/agent/` | Rule-based geometry/text agent + model-in-the-loop proposals + QA agent + training advisor. All outputs are proposals with provenance; nothing becomes ground truth without a human. |
| Dataset preparation | `kentucky/datasets/` | Quality gates/readiness, immutable versions with group-level (building) splits, exports: COCO det/inst, semantic masks, graph JSON, PyG |
| Catalog | `kentucky/catalog.py` | Approved templates with separate implementation vs checkpoint licenses and deployability |
| Training | `kentucky/training/` (Django-free) | LR-ASPP / SegFormer semantic seg, Mask R-CNN instance seg, GraphSAGE/GATv2/GCN node + relation GNNs; real metrics; JSONL event stream; checkpoints |
| Orchestration | `kentucky/orchestration/` | Persistent state machine, worker (`manage.py ka_worker`), claim/concurrency limits, heartbeats, cancel, runtime limits, retries for infra failures, crash recovery, cleanup, registration, billing |
| Providers | `orchestration/providers/` | `local` (subprocess, CPU; verified), `modal` (initial production GPU path; implemented, not run against Modal), `lambda` (provisioning + termination; container bootstrap not implemented) |
| Serving | `kentucky/inference/predictors.py`, `api.predict` | Same preprocessing as training; outputs in image px and original source coordinates; API-key auth, per-deployment rate limit, metering, version pinning/rollback |
| Billing | `kentucky/billing/` | Estimates, spend caps, idempotent ledger (infra cost vs customer charge), Stripe test-mode integration point (off until configured) |
| UI | `templates/kentucky/app.html`, `static/kentucky/*` | OT-01 design tokens (Kentucky AI / OpenTakeoff Premium): Dashboard, Dataset Center, Labeling Studio, Graph Studio, Catalog, Training wizard, Experiments, Registry, Deployments, API Keys, Usage & Billing, Organization |

## Process model

* **Web**: Django (Label Studio) serves UI + `/api/ka/` (session) + `/api/ka/v1/deployments/<slug>/predict` (API key).
* **Worker**: `python label_studio/manage.py ka_worker` claims queued jobs, launches the provider, tails
  `events.jsonl`, enforces limits, registers artifacts and records usage. Training never runs inside a
  request.
* **Training container**: `python -m kentucky.training.runner <job_dir>` — reads only `spec.json` and
  the exported dataset bundle, writes only `events.jsonl` and `artifacts/`. No database or secrets.

## Why not microservices

Everything except the training container lives in the existing Django process, reusing Label Studio's
auth, organizations, projects/tasks/annotations/predictions and storage conventions. The one hard
boundary is the training container, because it must run on rented GPUs and must be isolated from
customer-facing infrastructure.

## Integration with Kentucky AI Premium (private)

OpenTakeoff Premium is proprietary (all rights reserved) with AGPL portions; its code is **not copied**
into this public Apache-2.0 fork. The ingestion pipeline exposes a clean seam (`ingest/extract.py`
returns a `SheetExtract` with canonical primitives) where a private Premium indexer service can be
plugged in to supply higher-quality vectors, scale, schedules, symbols and room reconstruction. See
`LABEL_STUDIO_AUDIT.md` (code-reuse map).
