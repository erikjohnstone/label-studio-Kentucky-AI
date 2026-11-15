# Model Deployment and Inference API

## Deploying
Model Registry → **Deploy** (requires `commercially_deployable` license and an explicit confirmation).
Each deployment has a slug, active version, version history (set-version, rollback), status
(active / paused / deleted), per-minute rate limit, request and error counters.

## Calling a deployment
```
POST /api/ka/v1/deployments/{slug}/predict
Authorization: Bearer ka_...            # organization API key with "inference" scope
Idempotency-Key: <optional request id>  # retried requests are billed once
Content-Type: application/json
```

| Task | Input | Output |
|---|---|---|
| semantic / instance seg | `{"image": "<base64 PNG/JPEG>"}` or `{"sheet_id": 42}` | `predictions[]`: `label`, `confidence`, `bbox` [x,y,w,h], `polygon` (image px), `polygon_source` + `source_units` (when `sheet_id`), `page` |
| node classification | `{"graph": {...}}` or `{"sheet_id": 42}` | `nodes[]`: `id`, `label`, `confidence`, `probabilities`, `primitive_ids`, `bbox` |
| edge classification | same | `edges[]`: `id`, `source`, `target`, `candidate_type`, `label`, `confidence`, `probabilities` |

`sheet_id` inference on a raster sheet for graph models requires `allow_raster_inferred: true` (inputs
are inferred lines, not CAD geometry). Arbitrary PDF upload to the inference endpoint is not supported;
ingest the drawing into a dataset first (the ingestion pipeline is the supported preprocessing path).

Errors: `{"error": {"code", "message"}}` — 400 bad input, 401 bad/missing key, 404 unknown deployment
(also for other organizations' deployments), 409 paused, 429 rate limited (`Retry-After: 60`), 500.

```python
import base64, requests
r = requests.post(f"{BASE}/api/ka/v1/deployments/{slug}/predict",
                  headers={"Authorization": f"Bearer {KEY}", "Idempotency-Key": "job-17-sheet-3"},
                  json={"image": base64.b64encode(open("sheet.png", "rb").read()).decode()})
r.raise_for_status()
for p in r.json()["predictions"]:
    print(p["label"], p["confidence"], p["bbox"])
```

## Serving model
Predictions run in the web process with an LRU cache of loaded models (artifact SHA-256 verified on
load). Dedicated GPU hosting (`kind: dedicated`) is modelled in the schema and pricing but not
implemented; it would reuse the Modal container with a web endpoint.

## API keys
`/ka/keys/`: create (shown once; only SHA-256 stored), rotate (new key, old revoked atomically), revoke.
`last_used_at` is tracked; every prediction writes an audit entry.

## Hosting the platform
* Image: `docker build -f Dockerfile.kentucky -t ka-platform .` (Debian slim, Python 3.12 — PyTorch/PyG have no Alpine wheels).
* Two services from the same image: **web** `bash deploy/kentucky/start-web.sh` (migrations, static, gunicorn on `$PORT`)
  and **worker** `bash deploy/kentucky/start-worker.sh` (`ka_worker`: training jobs + always-on hosting meter).
* Railway: `deploy/kentucky/railway.json` (Dockerfile build, `/health/` check). Add Postgres and set `DJANGO_DB=default`,
  `POSTGRE_HOST/PORT/NAME/USER/PASSWORD`, `SECRET_KEY`, `LABEL_STUDIO_HOST`, the S3/R2 variables and (later) Stripe and GPU keys.
* Not deployed yet — no hosting service is connected.
