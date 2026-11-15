# Security and Data Privacy

| Control | Implementation |
|---|---|
| Tenant isolation | Every Kentucky row has `organization`; every API lookup filters by the caller's active organization and returns **404** for other orgs' objects (no existence oracle). Verified by `tests/test_security.py`. |
| Private storage | Keys are `org_<id>/...`; `storage.path()` rejects path traversal and cross-org prefixes. Sheet images are served only to signed-in members of the owning org. |
| Short-lived URLs | Exports and model downloads use signed URLs (5 min default, 1 h max) bound to the owning org prefix. |
| API keys | Org-scoped, `inference` scope, SHA-256 hashed at rest, shown once, rotate/revoke, last-used tracking. |
| Upload safety | Magic-byte type checks, 200 MB limit, encrypted PDFs and PDFs with JavaScript/Launch actions rejected, binary DXF rejected, decompression-bomb guard, page/entity limits. DWG/IFC refused with an explicit message. |
| Training isolation | Approved templates only (no customer code). The runner reads only the exported bundle and writes only events/artifacts; no DB access, no secrets. One process group per job (local) / one container per job (Modal). |
| Quotas & limits | Per-org concurrency, runtime limits, heartbeat timeouts, spend caps, per-deployment rate limits. |
| Audit log | Dataset create/update/delete, uploads, graph saves/reviews, object reviews, versions, exports, agent runs, proposal decisions, training create/authorize/cancel, model download/archive, deployments, key create/rotate/revoke, billing changes, every inference call. |
| Customer data deletion | `DELETE /api/ka/datasets/<id>/` removes originals, derived sheets, annotations (LS project), graphs, exports. |
| Consent | Customer data is never used for Kentucky AI models unless `allow_ka_model_training` is enabled per dataset; grants/revocations are timestamped in `consent_record`. |
| Agent safety | Drawing text is matched against keyword tables only (never interpreted as instructions); agents cannot authorize training or deploy models — those require explicit human confirmation. |
| Telemetry | Upstream defaults that sent errors to HumanSignal's Sentry, analytics, and PyPI version checks are off by default in this fork. |

## Known gaps (not production-ready yet)
* The S3/R2 backend (`KA_STORAGE_BACKEND=s3`) is implemented and tested against emulated S3 only; enable bucket
  encryption at rest on the R2/S3 side (or `KA_S3_SSE=1` for S3 SSE-AES256) and keep the bucket private —
  downloads still go through the platform's signed, org-checked URLs, never public bucket links.
* Rate limiter is in-process (use Redis for multi-process).
* Malware scanning of uploads (e.g. ClamAV) is not integrated; inputs are parsed by memory-safe Python
  libraries plus PDFium.
* Project roles beyond LS organization membership (annotator / reviewer / admin) are not enforced in
  Kentucky endpoints yet.
* Dependency vulnerability scanning (e.g. `pip-audit`) should run in CI.
