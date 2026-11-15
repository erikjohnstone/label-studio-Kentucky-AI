# Fireworks AI: Training and Serving Architecture (Public Docs Review)

_Researched 2026-11-15 from public Fireworks pages only. Nobody signed up, used API credentials, or connected a service._

This document covers what Fireworks AI publicly documents about training, datasets, models, deployments, auth, and billing. It then lists the patterns Kentucky AI copies in its own implementation. The two are kept apart on purpose:

- **Documented by Fireworks** means a fact that appears on a cited public page.
- **Pattern Kentucky AI adopts** is our own design. It is inspired by Fireworks but implemented by us, and it claims nothing about how Fireworks works internally.

Where a page did not settle a question, we say **Not verified**.

---

## 1. Headline finding: managed SFT/DPO no longer takes new jobs

**Documented by Fireworks.** The fine-tuning page says that managed supervised fine-tuning (SFT) and DPO/ORPO "no longer accept new jobs". Trained models remain deployable ([fine-tuning-models](https://docs.fireworks.ai/fine-tuning/fine-tuning-models)). The migration guide says:

- Managed SFT, DPO and ORPO jobs created before November 9, 2026 keep working. Queued or running jobs finish normally, and existing jobs can still be viewed, cancelled and deleted.
- Failed or cancelled jobs cannot be resumed.
- New training should use the **Training API**, starting from the cookbook recipes `sft_loop.py` and `dpo_loop.py`.

Source: [migrate-from-managed-training](https://docs.fireworks.ai/fine-tuning/migrate-from-managed-training.md). The page does not give a reason for the change.

The product page still describes three tiers ([fireworks.ai/product/training](https://fireworks.ai/product/training)):

- **Managed Training:** LoRA, billed per training token.
- **Serverless Training API:** LoRA, shared pool, billed per token.
- **Dedicated Training API:** LoRA or full-parameter, billed per GPU-hour. This is the tier for the largest MoE models.

## 2. Training methods

**Documented by Fireworks**

| Method | Where documented | Notes |
|---|---|---|
| SFT (text and vision-language) | [fine-tuning-models](https://docs.fireworks.ai/fine-tuning/fine-tuning-models), [cookbook/sft](https://docs.fireworks.ai/fine-tuning/training-api/cookbook/sft.md) | Vision SFT uses the same chat format, with image parts in user messages. |
| LoRA | same | Managed jobs train a LoRA by default. `lora_rank` goes up to 128, and rank 0 means full-parameter training. The default `--lora-rank` in firectl is 8. |
| DPO / ORPO | [cookbook/dpo](https://docs.fireworks.ai/fine-tuning/training-api/cookbook/dpo.md), DPO job API ([create-dpo-job](https://docs.fireworks.ai/api-reference/create-dpo-job.md)) | The migration guide says ORPO runs on Dedicated Training. |
| RL / RFT (GRPO or a custom objective) | [product/training](https://fireworks.ai/product/training), [rft-parameters-reference](https://docs.fireworks.ai/fine-tuning/rft-parameters-reference.md), RFT "step" APIs ([create-reinforcement-fine-tuning-step](https://docs.fireworks.ai/api-reference/create-reinforcement-fine-tuning-step.md)) | You supply prompts plus an evaluator: a reward function, a verifier, or an LLM judge. |
| Custom loops | [training-api/introduction](https://docs.fireworks.ai/fine-tuning/training-api/introduction.md) | You write the loop in Python and call `forward_backward` / `forward_backward_custom` and `optim_step`. Remote operations return futures, and the docs warn to call `.result()` on them or failures go unnoticed. |

The cookbook repo, [github.com/fw-ai/cookbook](https://github.com/fw-ai/cookbook), is Apache-2.0. It holds `training/recipes/` (one loop per file), `utils/`, `examples/`, `eval/` and `skills/`, and is published as `fireworks-training-cookbook`.

## 3. Dataset format and upload

**Documented by Fireworks**

- **Format:** JSONL with 3 to 3,000,000 lines. Each line is `{"messages": [...], "tools": [...]?}` in the OpenAI chat format, so "an existing OpenAI SFT dataset works without conversion".
  - Allowed roles are `system`, `user`, `assistant` and `tool`.
  - A per-message `weight` (0 excludes the message from the loss) or `trainable` flag controls which messages train ([fine-tuning-models](https://docs.fireworks.ai/fine-tuning/fine-tuning-models)).
- **Dataset resource:** `POST /v1/accounts/{account_id}/datasets` with `datasetId` and a `dataset` object ([create-dataset](https://docs.fireworks.ai/api-reference/create-dataset.md)).
  - The read-only `state` is `STATE_UNSPECIFIED`, `UPLOADING` or `READY`.
  - Other fields include `estimatedTokenCount` and `externalUrl`.
  - `sourceDatasetId` with `filter` derives a new dataset from an existing one using a SQL-like filter.
- **Upload:** `POST /v1/accounts/{account_id}/datasets/{dataset_id}:getUploadEndpoint` takes `filenameToSize` and returns `filenameToSignedUrls` ([get-dataset-upload-endpoint](https://docs.fireworks.ai/api-reference/get-dataset-upload-endpoint.md)). Separate pages cover "validate dataset upload" and "upload dataset files" (index: [llms.txt](https://docs.fireworks.ai/llms.txt)).
  - **Not verified:** the exact order of the signed-URL, upload and validate steps, the URL expiry, and the HTTP method used for the upload.
- **Size limits** beyond the line count: Not verified.

## 4. Training job API and lifecycle

**Documented by Fireworks.** For the (legacy) managed SFT job:

- **Get a job:** `GET https://api.fireworks.ai/v1/accounts/{account_id}/supervisedFineTuningJobs/{job_id}` ([get-supervised-fine-tuning-job](https://docs.fireworks.ai/api-reference/get-supervised-fine-tuning-job.md)).
- **Other operations:** create, list, delete and resume each have their own reference pages.

Key fields:

- `dataset` (required)
- `baseModel` or `warmStartFrom` (a PEFT addon to continue from)
- `outputModel` (defaults to the job ID)
- `state`, plus `status` (`code`, `message`)
- `jobProgress` (`percent`, `epoch`)
- `estimatedCost`, `createdBy` (an email), and `createTime` / `updateTime` / `completedTime`

**Documented `state` enum (20 values):**

| Group | States |
|---|---|
| Unset | `JOB_STATE_UNSPECIFIED` |
| Before training | `CREATING`, `CREATING_INPUT_DATASET`, `VALIDATING`, `PENDING` |
| Training | `RUNNING`, `RE_QUEUEING`, `IDLE`, `WRITING_RESULTS`, `PAUSED` |
| Finished | `COMPLETED`, `EARLY_STOPPED`, `FAILED`, `EXPIRED`, `CANCELLED` |
| Cancelling | `CANCELLING` |
| Deletion | `DELETING`, `DELETING_CLEANING_UP`, `DELETED` |
| Archived | `ARCHIVED` |

Every value carries the `JOB_STATE_` prefix. The grouping is our own reading; Fireworks documents only the list.

**CLI.** `firectl sftj` takes these flags: `--epochs`, `--learning-rate`, `--lora-rank`, `--batch-size-samples`, `--max-context-length`, `--evaluation-dataset`, `--output-model`, `--job-id`, `--use-reservation` and W&B flags. Use `firectl sftj get <JOB_ID>` to read a job ([fine-tuning-models](https://docs.fireworks.ai/fine-tuning/fine-tuning-models)).

**Training API lifecycle** ([introduction](https://docs.fireworks.ai/fine-tuning/training-api/introduction.md)):

- On Serverless, the service manages the session.
- On Dedicated, you must close trainers and delete or scale down deployments yourself.
- Fireworks handles trainer creation, health checks and reconnects.

## 5. Base model catalog

**Documented by Fireworks.** Serverless and Dedicated training share one catalog. "Availability is set per model, by parameter mode (LoRA or full-parameter) and method (SFT, DPO, and RL)" ([fine-tuning/models](https://docs.fireworks.ai/fine-tuning/models.md)).

- Vision support covers **vision-language models** only.
- No segmentation, detection or graph models are listed.
- The fetched page did not include the per-model list (Not verified).

## 6. Checkpoints and evaluation

**Documented by Fireworks**

**Checkpoints** ([introduction](https://docs.fireworks.ai/fine-tuning/training-api/introduction.md)):

- **Base snapshots** are full anchors: the adapter for LoRA, or the full weights.
- **Delta snapshots** record changes relative to a prior full-parameter base and are not promotable.
- `FireworksClient` lists checkpoints and **promotes** a checkpoint to a model without a live trainer.

**Evaluation** ([evaluating-fine-tuned-models](https://docs.fireworks.ai/fine-tuning/evaluating-fine-tuned-models.md)): you define the metric yourself by running `sampler.sample()` over held-out prompts. There are three paths:

1. Serverless checkpoint sampling, using `save_weights_for_sampler`.
2. Serverless LoRA inference on a promoted model.
3. A preemptible deployment (`firectl deployment create ... --preemptible`).

The docs mark serverless sampling and preemptible deployments as "training evals and other non-production workloads only".

Managed SFT also accepts an evaluation dataset uploaded in advance (`--evaluation-dataset`).

## 7. Model registry ("models" resource)

**Documented by Fireworks** ([get-model](https://docs.fireworks.ai/api-reference/get-model.md))

- **Path:** `GET /v1/accounts/{account_id}/models/{model_id}`. The resource name is `accounts/<ACCOUNT_ID>/models/<MODEL_ID>`.
- **`kind`:** `HF_BASE_MODEL`, `HF_PEFT_ADDON`, `HF_TEFT_ADDON`, `FLUMINA_BASE_MODEL`, `FLUMINA_ADDON`, `DRAFT_ADDON`, `LIVE_MERGE`, `CUSTOM_MODEL`, `EMBEDDING_MODEL`, `SNAPSHOT_MODEL`.
- **`state`:** `UPLOADING` or `READY`.
- **`public`:** boolean; `true` makes the model publicly readable.
- **`peftDetails`:** `baseModel`, `r` (4 to 64), `targetModules`.
- **`deployedModelRefs[]`:** each entry has `state` (`DEPLOYING`, `DEPLOYED`, `UPDATING`, `UNDEPLOYING`) and a `default` flag.
- **Custom uploads:** models can be uploaded through upload and validate endpoints ([uploading-custom-models](https://docs.fireworks.ai/models/uploading-custom-models.md)).
- **Weights:** "you keep the resulting weights". LoRA adapters download in Hugging Face PEFT format and need the base model to run ([product/training](https://fireworks.ai/product/training)).

## 8. Serverless vs on-demand (dedicated) deployments

**Documented by Fireworks**

**Serverless** ([serverless/overview](https://docs.fireworks.ai/serverless/overview.md)):

- Multi-tenant hosting of popular models.
- Billed per token: input, cached input (50% of the input rate by default) and output.
- Rate limits are adaptive tokens per minute, set by spend tier.
- LoRA serving works only on select base models. The Training API intro says "Serverless per-token serving of your own adapter is not available" for Training-API LoRAs; they deploy on-demand.
- The two pages appear to differ in scope; this is Not verified further.

**On-demand** ([ondemand-deployments](https://docs.fireworks.ai/guides/ondemand-deployments.md)):

- Dedicated GPUs, "billed by GPU-second".
- **Deployment shapes:** fast, throughput, minimal or `default`. The docs warn against deploying without a shape.
- **States:** `CREATING`, `READY`, `UPDATING`, `DELETING`, `DELETED`, `FAILED`, plus `PARTIAL_READY` for preemptible deployments.
- **Scaling:** a deployment scales to zero after 1 hour idle by default. Deployments with min replicas set to 0 are deleted after 7 days without traffic. A cold request returns 503, so clients must retry.
- **Querying:** use the model name `accounts/<ACCOUNT_ID>/deployments/<DEPLOYMENT_ID>` against `https://api.fireworks.ai/inference/v1` (OpenAI-compatible).

## 9. API keys and authentication

**Documented by Fireworks**

- **Header:** REST requests send `Authorization: Bearer <API_KEY>` ([api-reference/introduction](https://docs.fireworks.ai/api-reference/introduction.md)).
- **Creating keys:** with `firectl api-key create` or in the dashboard.
- **Service accounts** ([service-accounts](https://docs.fireworks.ai/accounts/service-accounts.md)) are non-human identities:
  - Create one with `firectl user create --service-account` and give it a key with `firectl api-key create --service-account <name>`.
  - The role defaults to `user`.
  - Service accounts share the account's quotas, and usage is tracked per account.
- **Finer per-key scoping:** Not verified.

## 10. Billing units

**Documented by Fireworks** ([pricing](https://fireworks.ai/pricing), [product/training](https://fireworks.ai/product/training))

| Surface | Unit |
|---|---|
| Managed Training (legacy) | per training token, rate by model size |
| Serverless Training API | per 1M tokens, priced separately for prefill / sample / train. Repeated prefixes get 80% off prefill. |
| Dedicated Training API | per GPU-hour, "starting at $8.00" |
| Serverless inference | per 1M input / cached-input / output tokens |
| On-demand deployments | per GPU-second. H100 and H200 list at $8.00/h, B200 at $13.00/h. Region-restricted deployments cost 1.5x. |
| Serving a fine-tuned model | no extra fee: "You pay for the deployment by the GPU-second, plus the cost of the training job." |

Usage and billing export APIs also exist ([get-billing-usage](https://docs.fireworks.ai/api-reference/get-billing-usage.md)).

## 11. Account and model ownership, isolation

**Documented by Fireworks**

- Every resource is namespaced under `accounts/{account_id}/...`: datasets, jobs, models and deployments.
- Models carry a `public` flag.
- Customers keep their trained weights.
- **Zero Data Retention** is an Enterprise, account-wide policy. It rejects fine-tuning, dataset uploads and custom model uploads, but does not delete data already stored ([zero-data-retention](https://docs.fireworks.ai/accounts/zero-data-retention.md)).
- **Not verified:** any explicit statement about tenant isolation, or about whether customer data trains Fireworks models. We do not speculate on either.

---

## 12. Why Fireworks fine-tuning does not transfer to segmentation or GNN training

Fireworks' training surfaces are built for **token-based LLMs and VLMs**:

- **Data:** the dataset schema is chat `messages` JSONL.
- **Billing:** the units are training, prefill and sample **tokens**.
- **Catalog:** the base models are LLM and VLM checkpoints. Model kinds are `HF_BASE_MODEL` / `HF_PEFT_ADDON`, and LoRA targets transformer modules.
- **Evaluation:** samplers generate text.
- **Serving:** the endpoint is chat or completions.

Kentucky AI's workloads have none of these properties:

- **Semantic or instance segmentation** of drawing rasters (SegFormer, Mask2Former, SAM 2) needs pixel-mask datasets, dense losses such as cross-entropy, Dice or mask losses, and mIoU or PQ metrics.
- **Graph models over CAD primitives** (PyG GAT/GNN) need graph-structured batches and node or edge classification losses.

No documented Fireworks surface accepts either kind of data or model. The Training API's custom loss still runs over token "Datums" on a supported LLM or VLM base model. Fireworks therefore cannot be our training backend for these models.

What does transfer is the **resource and lifecycle design**, listed below.

## 13. Patterns Kentucky AI adopts (our own implementation)

None of the following is a Fireworks feature. Each item names the Fireworks idea it borrows.

1. **Account-namespaced resources.** Every Dataset, TrainingJob, ModelVersion and Deployment row is keyed by organization, mirroring the `accounts/{id}/...` naming. Every query filters by org.
2. **Dataset as a versioned, validated resource**, with states `UPLOADING → VALIDATING → READY / FAILED`. Uploads go through signed URLs, then a server-side validation step. We add a VALIDATING state that the Fireworks dataset enum does not have.
3. **An explicit job state machine** modelled on the documented SFT enum but smaller: `PENDING`, `PROVISIONING`, `RUNNING`, `WRITING_RESULTS`, `COMPLETED`, `FAILED`, `CANCELLING`, `CANCELLED`, `EXPIRED`. Terminal states are immutable.
4. **`estimatedCost` on the job record**, with actual cost metered in GPU-seconds from the provider (Modal or Lambda). This matches Fireworks' GPU-second unit for dedicated compute.
5. **Checkpoint, then promote, then model.** Intermediate checkpoints are not deployable until promoted to a ModelVersion, as with Fireworks' promotable base snapshots.
6. **Evaluation decoupled from training.** We run a held-out evaluation with task metrics (mIoU, PQ, edge F1) before a model can be promoted to "production".
7. **Separate serving tiers:** shared batch inference versus a dedicated GPU deployment that scales to zero, with clients told to retry on cold start.
8. **Service-account API keys** for automation, distinct from human users, with all usage rolled up per org for billing.
9. **Customers own their weights.** Exportable artifacts per org, and a `public=false` default.

## Sources

- https://fireworks.ai/
- https://fireworks.ai/product/training
- https://fireworks.ai/pricing
- https://docs.fireworks.ai/llms.txt
- https://docs.fireworks.ai/fine-tuning/fine-tuning-models
- https://docs.fireworks.ai/fine-tuning/migrate-from-managed-training.md
- https://docs.fireworks.ai/fine-tuning/training-api/introduction.md
- https://docs.fireworks.ai/fine-tuning/models.md
- https://docs.fireworks.ai/fine-tuning/evaluating-fine-tuned-models.md
- https://docs.fireworks.ai/api-reference/introduction.md
- https://docs.fireworks.ai/api-reference/get-supervised-fine-tuning-job.md
- https://docs.fireworks.ai/api-reference/create-dataset.md
- https://docs.fireworks.ai/api-reference/get-dataset-upload-endpoint.md
- https://docs.fireworks.ai/api-reference/get-model.md
- https://docs.fireworks.ai/guides/ondemand-deployments.md
- https://docs.fireworks.ai/serverless/overview.md
- https://docs.fireworks.ai/serverless/pricing.md
- https://docs.fireworks.ai/accounts/service-accounts.md
- https://docs.fireworks.ai/accounts/zero-data-retention.md
- https://github.com/fw-ai/cookbook
