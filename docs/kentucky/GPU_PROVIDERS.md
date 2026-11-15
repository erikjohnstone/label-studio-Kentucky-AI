# GPU Providers

Kentucky AI owns the customer-facing API and orchestrator; providers only supply compute. Customers
never need their own provider account. All providers run the same container entrypoint
(`kentucky.training.runner`) on the same job directory format.

| Provider | Status | Notes |
|---|---|---|
| `local` | **Implemented and verified** | Child process per job (process group), CPU, used by tests and `cpu-local` tier |
| `modal` | **Implemented, not run against Modal** (no credentials attached) | Selected initial production GPU path: serverless GPU functions, per-second billing, no idle instances to leak. App definition: `deploy/modal/ka_trainer.py`; adapter: `orchestration/providers/modal.py` |
| `lambda` | **Partial** | Instance launch / status / terminate via the Lambda Cloud API; the SSH bootstrap that starts the container on the instance is **not implemented**, so `check_available()` refuses to launch (no idle billable instance can be created) |

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

## Enabling Lambda (operator, after bootstrap is implemented)
`LAMBDA_API_KEY`, `KA_LAMBDA_REGION`, `KA_LAMBDA_SSH_KEY`, `KA_LAMBDA_BOOTSTRAP=True`. The API base is
configurable with `KA_LAMBDA_API_BASE` (default `https://cloud.lambda.com/api/v1`, Bearer auth, verified against
Lambda's OpenAPI spec v1.10.0). Launch accepts cloud-init `user_data`, which is the intended bootstrap path.
