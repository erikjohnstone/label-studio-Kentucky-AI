# Label Studio Audit and Code-Reuse Map

## Upstream baseline
* Label Studio `1.24.0.dev0` (develop, Nov 2026), Apache-2.0 (`LICENSE`). Django 5.2 + DRF backend,
  React/Nx frontend (`web/`, built with bun), SQLite by default, PostgreSQL supported.
* Auth/users: `users/`, `jwt_auth/`, `session_policy/` (session timeout middleware requires a real login).
* Tenancy: `organizations/` (Organization, OrganizationMember, `user.active_organization`).
* Data: `projects/`, `tasks/` (Task, Annotation with `parent_prediction`, Prediction with
  `model_version`), `data_import/`, `data_export/` (via `label-studio-sdk` converters), `io_storages/`
  (S3, GCS, Azure, Redis, local).
* ML: `ml/` (connects external **ML backends** over HTTP: predict, interactive pre-annotation, `train`
  webhook), `ml_models/` + `ml_model_providers/` (Prompts / LLM labeling — the README states the
  feature is used by Label Studio **Enterprise**), `fsm/` (state machine for project/task states).
* Background jobs: `django_rq` with synchronous fallback when Redis is absent.

## AI / agentic capabilities — what is actually in the open-source edition

| Capability | In this fork (OSS) | Notes |
|---|---|---|
| Model-assisted pre-annotation | Yes — ML backend predictions + interactive mode | Requires running an ML backend server |
| Training trigger from LS | Yes — `MLBackend.train` webhook | Training logic lives in the external backend |
| Prompts / LLM labeling | Models present (`ml_models`), feature used by Enterprise | Not used here |
| Reviewer workflow, agreement, quality dashboards | Not in OSS | Implemented by Kentucky (`objects/review`, readiness, disagreement report) |
| Active learning loop | Not in OSS | Kentucky: model-in-the-loop proposals (`propose-from-model`) |
| Autonomous labeling agents | Not in OSS | Kentucky rule-based agent + optional LLM planner integration point |

## Code-reuse map

| Need | Existing functionality | Reused? | Integration point / decision | License |
|---|---|---|---|---|
| Users, orgs, sessions | LS users/organizations | **Reused** | `security.org_of`, org FK on every Kentucky row | Apache-2.0 |
| CV annotation editor | LS editor (polygon, rect, brush, keypoint, zoom/pan, vertex editing) | **Reused** | Generated labeling config per taxonomy version; `labeling.sync_from_label_studio` | Apache-2.0 |
| Predictions in editor | LS Prediction / `parent_prediction` | **Reused** | Agent proposals pushed as predictions; acceptance tracked as `agent_accepted` | Apache-2.0 |
| Export converters | `label-studio-sdk` brush RLE decode | **Reused** (RLE) | COCO/semantic/PyG exporters are new (construction schema, splits, review gates) | Apache-2.0 |
| ML backend protocol | `ml/` | Not needed | Kentucky trains/serves natively; a custom ML backend can still be attached | Apache-2.0 |
| Vector PDF engine | Premium `backend/pdfdoc.py` (pypdfium2 + pypdf + reportlab), `sheet_image.py` | **Not copied** | New extractor on pdfplumber + pypdfium2; seam for a private Premium indexer service | Premium: proprietary |
| pdf.js vector geometry, rooms, symbols, sheet graph | Premium `frontend/src/lib/*` (TS) | **Not copied** | Could run as private Node service via the same seam | Proprietary |
| Scale / sheet index / schedules | Premium `plan_scale.py`, `sheet_index.py`, `reading/vectorgrid.py` | **Not copied** | Future private service providing schedule-derived label suggestions | Proprietary |
| SAM2 click-to-room | Premium `sam_room.py` (private weights) | **Not copied** | Catalog lists SAM 2 (Apache-2.0) as an assist integration point | Proprietary / Apache-2.0 |
| Agent tool-calling | Premium `agent_tools.py`, `agent_runtime/` | **Not copied** | `agent/` exposes deterministic tools; an LLM planner can be added behind an operator flag | Proprietary |
| Training capture JSONL | Premium `takeoff_capture.py` | **Not copied** | Canonical schema covers the same fields (verts, bbox, vector refs, reviewed, origin) | Proprietary |
| Stripe / R2 / Clerk | Premium `billing.py`, `r2_pool.py`, `clerk_auth.py` | **Not copied** | Ledger + Stripe test-mode adapter; storage abstraction ready for R2 | Proprietary |
| Design system | Premium `styles/tokens.css`, kentucky-ai.com | **Values reproduced** (colors, type, spacing, component specs) | `static/kentucky/ka.css`; no proprietary source files or logo artwork copied | — |
| GNN / checkpoints | none found in Premium (tree models + private SAM weights only) | — | No Kentucky AI checkpoints offered in the catalog | — |

## Missing functionality that was built
Dataset Center, versioned taxonomy, review gates, canonical CV+graph schema, ingestion with vector
extraction/coordinate mapping/tiles/OCR, Graph Studio, agents with provenance, immutable versions +
leak-free splits + exports, model catalog with licensing, real training (seg / instance / GNN), job
orchestration, registry, deployments, API keys, metering/billing, audit log, platform UI.

## Upstream update path
Kentucky code is isolated in `label_studio/kentucky/`, `docs/kentucky/` and `deploy/modal/`. Upstream
files changed: `core/settings/base.py` (app registration, analytics + version-check defaults),
`core/settings/label_studio.py` (Sentry defaults), `core/urls.py` (one include). Merge upstream normally;
conflicts are limited to those lines.
