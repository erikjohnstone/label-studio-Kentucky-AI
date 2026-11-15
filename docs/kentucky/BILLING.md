# Usage and Billing

* **Ledger** (`LedgerEntry`): append-only, one row per billable event with a unique
  `idempotency_key` (`job:<id>:compute`, `job:<id>:platform_fee`, `inf:<deployment>:<request-id>`).
  Each row stores **infra cost** and **customer charge** separately.
* **Training**: charged on actual runtime × tier rate, capped at the authorized maximum, plus a
  platform fee on completed jobs (not on `cpu-local`). Cancelled and timed-out jobs pay compute used.
  Jobs that fail due to infrastructure/provider faults are recorded with **zero** charge.
* **Inference**: per request by task (`inference_per_1k`), infra cost tracked alongside.
* **Spend caps**: monthly cap per organization; authorization reserves the job's maximum until it ends.
* **Payment method**: `none` / `test_card` / `active`. Paid compute requires a method or prepaid credit.
* **Stripe**: `billing/ledger.submit_to_stripe` creates invoice items with the ledger key as
  `Idempotency-Key`. It is **inactive** unless `KA_STRIPE_SECRET_KEY` is set; live keys are blocked
  unless `KA_STRIPE_LIVE=1`. No Stripe calls were made during development.
* **Rates**: `billing/pricing.py` contains **placeholder** development rates (flagged in API and UI).
  Configure `KA_PRICING` with contracted provider costs and customer prices before charging.
* **Dashboard**: `/ka/billing/` shows spend vs cap, payment method, usage by kind, rates and history.

## Always-on hosting
A deployment can be **Pay per request** (default) or **Always on** (`kind: dedicated`). Always-on keeps the
model loaded and the worker (`ka_worker`) accrues one ledger entry per deployment-hour
(`hosting:<deployment>:<hour start>` — idempotent) at `dedicated_hosting_per_hour` (customer) and
`dedicated_hosting_infra_per_hour` (our cost). Pausing or deleting bills the partial hour pro-rata; resuming
restarts the clock. Creating one is refused if one hour would pass the monthly limit, and a running one is
paused automatically (with an audit entry) when the next hour would pass it.
