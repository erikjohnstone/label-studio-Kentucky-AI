# GPU Providers

Kentucky AI owns the customer-facing API and orchestrator; providers only supply compute. Customers
never need their own provider account. All providers run the same container entrypoint
(`kentucky.training.runner`) on the same job directory format.

| Provider | Status | Notes |
|---|---|---|
| `local` | **Implemented and verified** | Child process per job (process group), CPU, used by tests and `cpu-local` tier |
| `modal` | **Implemented; verified end to end against a stand-in Modal SDK** (`tests/test_modal_provider.py`), never run on Modal (no credentials) | Selected initial production GPU path: serverless GPU functions, per-second billing, no idle instances to leak. App: `deploy/modal/ka_trainer.py` (body in `training/modal_entry.py`); adapter: `orchestration/providers/modal.py` |
| `lambda` | **Implemented; verified end to end against a fake Lambda API + emulated S3** (`tests/test_lambda_provider.py`), never run on Lambda | Launch with a cloud-init bootstrap: the instance downloads the job + training package via presigned URLs, runs `training.remote_agent` → `training.runner`, streams events, uploads artifacts and `done.json`, powers itself off; the orchestrator always terminates it. Needs the S3/R2 storage backend |

## Spending safety
* Paid providers are disabled unless an operator sets `KA_ENABLE_PAID_COMPUTE=1`.
* Authorization requires: validated job, explicit confirmation + max spend, spend cap headroom
  (month-to-date + reserved active jobs), payment method or prepaid credit, provider configured.
* Runtime limit and heartbeat timeouts kill jobs; `cleanup()` is called on every terminal path.
* During development everything defaults to `cpu-local` (free).

## Enabling Modal (operator)
1. `pip install modal`; set `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` for Kentucky AI's workspace.
2. `modal deploy deploy/modal/ka_trainer.py` (creates app `ka-trainer` and volume `ka-training-runs`).
3. Set `KA_ENABLE_PAID_COMPUTE=1` and real rates in `KA_PRICING`.
4. Run one small job end to end and record the result in `TEST_RESULTS.md` before calling it production-ready.
**Blocker before production:** Modal's Terms of Service limit use to the customer's "internal business" (§1.1) and
prohibit resale / third-party access (§1.3(c)). Running training on behalf of Kentucky AI's customers must be
confirmed with Modal (e.g. a written agreement) before this path goes live. Modal call results expire after 7 days
and functions time out after 24 h max; jobs are capped below that.

## Enabling Lambda (operator)
Set `LAMBDA_API_KEY`, `KA_LAMBDA_REGION`, `KA_LAMBDA_SSH_KEY` (an SSH key name registered with Lambda — the launch
API requires exactly one), the S3/R2 storage backend (`KA_STORAGE_BACKEND=s3`, bucket, endpoint, keys) and
`KA_ENABLE_PAID_COMPUTE=1`. The API base is configurable with `KA_LAMBDA_API_BASE` (default
`https://cloud.lambda.com/api/v1`, Bearer auth, per Lambda's OpenAPI spec v1.10.0). The instance never receives
platform credentials — only presigned URLs scoped to its own job prefix, valid for the run time + 3 h.
Before production: run one small job on the cheapest instance type and record it in `TEST_RESULTS.md`.
