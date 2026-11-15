# ML Platform Research: Annotation, Training, Compute, Graph Models, Licenses

_Researched 2026-11-15 from public official documentation. No sign-ups, credentials or service connections were used. "Not verified" means the official pages we read did not settle the point._

---

## 1. Roboflow: label → version → train → deploy

The lifecycle runs in four steps:

1. Upload images and annotate them.
2. **Generate a dataset version.**
3. Train from that version.
4. Deploy to a hosted endpoint.

**Dataset versions** ([docs](https://docs.roboflow.com/datasets/dataset-versions)):

- A version is a "point-in-time snapshot" of images and labels, with train/valid/test counts and sequential numeric IDs.
- **Preprocessing** (resize, auto-orient, grayscale) and **augmentation** (rotate, brightness, noise, crop, flip, exposure) are chosen when the version is generated.
- A version is required for training. Training metrics (mAP, precision, recall) are attached to the version.
- Versions export in training-ready formats; the export runs asynchronously.
- Whether versions are strictly immutable: Not verified. The docs say "snapshot" but do not say immutable.

**Training and deploy** ([model training guide](https://docs.roboflow.com/guides/model-training.md)):

- The quickstart trains RF-DETR (Apache-2.0) from a version, shows live training graphs, and reports mAP, precision, recall and F1 when done.
- A trained version gets a hosted **Serverless API** endpoint (`serverless.roboflow.com`). It can also run inside a Workflow or on self-hosted Inference.

**Takeaway for us:** an immutable dataset version with a recorded preprocessing/augmentation recipe should be the unit that every training job references.

## 2. Hugging Face AutoTrain and Jobs

**AutoTrain**

- The docs now say: "This project is no longer maintained". They recommend Axolotl, TRL or `transformers.Trainer` instead ([AutoTrain docs](https://huggingface.co/docs/autotrain/index)).
- It ran as a Space with the AutoTrain Docker image or locally (`autotrain-advanced`), covering NLP, CV (including object detection) and tabular tasks.

**HF Jobs** ([guide](https://huggingface.co/docs/huggingface_hub/guides/jobs)) runs Docker-style jobs on HF hardware:

- Start a job with `run_job(image, command, flavor, timeout, env, secrets, volumes)` or `hf jobs run` / `hf jobs uv run`.
- Status stages include `RUNNING`, `SCHEDULING`, `COMPLETED`, `CANCELED`, `ERROR` and `DELETED`.
- Management calls are `inspect_job`, `fetch_job_logs`, `fetch_job_metrics`, `cancel_job`, `wait_for_job` and scheduled jobs.
- **Timeout:** 30 minutes by default unless `timeout` is set.
- **Billing:** pay-as-you-go per second and requires a positive credit balance. For example, `a100-large` costs $2.50/h and `h200` costs $5/h.
- Hub repos or Storage Buckets can be mounted as volumes, which is useful for checkpoints.

## 3. CVAT annotation architecture

- CVAT is a server (Django plus workers, run with Docker Compose).
- Its data model is projects → tasks → jobs: a task's frames are split into jobs, which are assigned to annotators.
- **Auto-annotation** runs through **Nuclio serverless functions** ([installation guide](https://docs.cvat.ai/docs/administration/advanced/installation_automatic_annotation/)):
  - Start the stack with `docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml up -d`.
  - The `nuctl` version must match the one pinned in that compose file.
  - Deploy models with `./serverless/deploy_cpu.sh <dir>` or `./serverless/deploy_gpu.sh <dir>`, or directly with `nuctl deploy --file .../function.yaml --platform local`.
  - GPU functions need the NVIDIA Container Toolkit, and GPU memory limits how many functions can be deployed.
  - Function kinds include detectors, interactors and trackers ([serverless tutorial](https://docs.cvat.ai/docs/manual/advanced/serverless-tutorial/)). The full list of kinds is Not verified on the current page.

**Takeaway for us:** model serving is a separate, independently deployed service called over HTTP by the annotation server. That is the same shape as Label Studio's ML backend.

## 4. Label Studio ML backend and edition boundaries

**ML backend** ([repo](https://github.com/HumanSignal/label-studio-ml-backend), Apache-2.0; [guide](https://labelstud.io/guide/ml)):

- Subclass `LabelStudioMLBase` and implement two methods:
  - `predict(self, tasks, context, **kwargs)` returns predictions. `context` carries interactive-labeling input.
  - `fit(self, event, data, **kwargs)` runs training or other persistent work and fires on webhook events.
- Helpers are `self.model_version`, `self.set/get`, and `self.get_local_path(url, task_id)`.
- The backend runs with `docker-compose up` (port 9090) or `label-studio-ml start`. It needs `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY` to fetch media.
- Examples include `segment_anything_2_image`, `segment_anything_model`, `yolo`, `mmdetection` and `grounding_sam`.

**Webhook events** ([reference](https://labelstud.io/guide/webhook_reference)):

- `TASK(S)_CREATED`, `TASK(S)_DELETED`
- `ANNOTATION_CREATED`, `ANNOTATION_UPDATED`, `ANNOTATION(S)_DELETED`
- `PROJECT_CREATED`, `PROJECT_UPDATED`, `PROJECT_DELETED`
- `START_TRAINING`, sent to the ML backend when a user clicks "Start Training"

**Interactive pre-annotation:** "smart" tools work for Rectangle, Ellipse, Polygon, KeyPoint and Brush.

**Which features are open source and which are paid**, per the official comparison page ([label_studio_compare](https://labelstud.io/guide/label_studio_compare)):

| Feature | Community (OSS) | Starter Cloud | Enterprise |
|---|---|---|---|
| Custom ML backends, predictions from connected models | Yes | Yes | Yes |
| Prompts / LLM "automated pre-labeling" | No | Limited trial | Yes |
| Active learning loops | No | No | Yes |
| Agreement metrics | No | Limited | Yes |
| Assign reviewers / review workflow | No | Yes | Yes |
| Assign tasks | No | Yes | Yes |
| Project dashboards | No | No | Yes |

Two further statements back this up:

- The ML guide says: "You can use Label Studio Enterprise to build an automated active learning loop". In Community, active learning can only be approximated by sorting tasks manually.
- A HumanSignal support article says Prompts is not available in open-source Label Studio. Enterprise on-prem gained Prompts in 2.25.0 ([release notes](https://docs.humansignal.com/guide/release_notes/onprem/2.25.0.html)).

**Implication for Kentucky AI:** in our fork, active-learning orchestration, agreement scoring and review queues must be **our own code** built on the OSS ML-backend and webhook primitives. We must not copy Enterprise code or present it as Label Studio functionality.

## 5. Modal

- **Functions** ([modal.Function](https://modal.com/docs/reference/modal.Function)):
  - `modal.Function.from_name(app_name, name, *, version=None, environment_name=None)` is the current way to look up a deployed function. Nothing on the page marks it deprecated.
  - `.remote()` blocks until the result is ready. `.spawn()` returns a `modal.FunctionCall` immediately.
  - `.spawn_map()` cannot yet return results programmatically.
- **FunctionCall** ([reference](https://modal.com/docs/reference/modal.FunctionCall)):
  - `FunctionCall.from_id(function_call_id)`.
  - `.get(timeout=None)` waits indefinitely by default. `timeout=0` polls.
  - The job-queue guide catches **`TimeoutError`** while the call is still running and returns HTTP 202 ([job-queue guide](https://modal.com/docs/guide/job-queue)).
  - Results remain available for **7 days**. After that, `modal.exception.OutputExpiredError` is raised.
  - `.cancel(terminate_containers=False)` cancels without retrying.
- **Volumes** ([modal.Volume](https://modal.com/docs/reference/modal.Volume)):
  - `Volume.from_name(name, *, create_if_missing=False, version=None)`.
  - Methods include `listdir(path, recursive=False)`, `iterdir` (recursive by default), `read_file` (chunked; "primarily intended to be used outside of a Modal App"), `batch_upload`, `copy_files`, `commit()` and `reload()` (the last two run inside a container).
  - Nothing is marked deprecated except `.resolve()` → `.hydrate()`. A v2 backend exists behind `version=2` and is marked experimental.
- **Timeouts** ([guide](https://modal.com/docs/guide/timeouts)): the default is 300 s, and the range is 1 s to **24 h**. `startup_timeout` is configured separately. Training longer than 24 h must checkpoint and resume.
- **Pricing** ([pricing](https://modal.com/pricing)):
  - Billed per second with no idle charge. Examples: H100 $0.001097/s (about $3.95/h), A100-80GB $0.000694/s, L4 $0.000222/s.
  - CPU and memory are billed separately. Volumes cost $0.09/GiB-month, with 1 TiB free.
  - Region pinning applies a 1.15–1.75x multiplier, and containers stay alive (and billed) for 60 s after the last input by default.
  - Plans: Starter ($0 base, $30/month credits, 10 GPU concurrency); Team ($250/month, 50 GPU concurrency); Enterprise.
- **Running workloads for your own customers** ([Terms](https://modal.com/legal/terms), effective May 2026):
  - §1.1 limits use to "solely for Customer's internal business".
  - §1.3(c) forbids you to "rent, resell or otherwise allow any third party direct access to or use of the Service".
  - "End users" and "customer applications" are not defined.
  - Our reading, **not legal advice**: a backend where our servers call Modal and customers never touch Modal is less clearly prohibited than giving customers direct access. It is still ambiguous under the "internal business" wording. **Not verified as permitted.** Get written confirmation from Modal, or an Enterprise agreement, before production SaaS use.

## 6. Lambda Cloud API (current)

Taken from the official OpenAPI spec `https://docs.lambda.com/api/cloud/spec.json` (v1.10.0) and the [API docs](https://docs.lambda.com/api/cloud).

**Servers.** The current server and both older ones serve the same API:

| Base URL | Spec status |
|---|---|
| `https://cloud.lambda.com/` | Production |
| `https://cloud.lambda.ai/` | "Secondary production server (deprecated)" |
| `https://cloud.lambdalabs.com/` | "Tertiary (deprecated)" |

The docs moved too: `docs.lambda.ai` now 301-redirects to `docs.lambda.com`.

**Endpoints**, all under `/api/v1`:

| Operation | Method and path |
|---|---|
| Launch | `POST /instance-operations/launch` |
| List running instances | `GET /instances` |
| Get one instance | `GET /instances/{id}` |
| Update instance details | `POST /instances/{id}` |
| Terminate | `POST /instance-operations/terminate` with body `{"instance_ids": [...]}` |
| Restart | `POST /instance-operations/restart` |
| List instance types | `GET /instance-types` |
| Other resources | `GET /images`, `GET /regions`, `/ssh-keys`, `/filesystems`, `/firewall-rulesets` |

**Launch request body:**

- **Required:** `region_name`, `instance_type_name`, `ssh_key_names` (exactly one key).
- **Optional:** `file_system_names`, `file_system_mounts`, `hostname`, `name` (64 characters or fewer), `image`, **`user_data`**, `tags`, `firewall_rulesets`, `workspace_id`.
- **`user_data`:** "cloud-init user-data" in plain text, at most 1 MB. **Cloud-init is supported.**
- **No `quantity` field** appears in the current schema.
- **Response:** `{"instance_ids": [...]}`.

**Auth:**

- **Bearer** (`Authorization: Bearer <api_key>`) is recommended.
- **Basic** still works "for backward compatibility": either `Basic base64(api_key:)` or `Basic <api_key>`.

**Rate limits:** about 1 request per second in general. Launch is limited to 1 per 12 s (5 per minute).

## 7. PyTorch Geometric

- **Heterogeneous graphs** ([docs](https://pytorch-geometric.readthedocs.io/en/latest/notes/heterogeneous.html)):
  - `HeteroData` stores node types and `(src, rel, dst)` edge types.
  - Model inputs come from `x_dict` / `edge_index_dict`, and `metadata()` returns the types.
  - `to_hetero(model, metadata, aggr=...)` converts a homogeneous model. `HeteroConv({edge_type: conv})` gives each relation its own operator.
  - Lazy `-1` input sizes need one forward pass before training.
- **Batching** ([docs](https://pytorch-geometric.readthedocs.io/en/latest/advanced/batching.html)):
  - `DataLoader` stacks graphs block-diagonally and offsets `edge_index` by the cumulative node count.
  - `__inc__` / `__cat_dim__` customise how attributes are collated, and `follow_batch` builds extra batch vectors.
  - Edge features are concatenated on dim 0. This is our inference from the general rule; the page does not say it explicitly.
- **Link and edge tasks** ([loader docs](https://pytorch-geometric.readthedocs.io/en/latest/modules/loader.html)):
  - `LinkNeighborLoader(edge_label_index, edge_label, neg_sampling)` supports binary and triplet negative sampling. `neg_sampling_ratio` is deprecated.
  - The docs warn that supervision edges can leak into message passing. Use `RandomLinkSplit(disjoint_train_ratio=...)` to keep them separate.
  - **Edge classification** means using `edge_label` with categorical labels.

## 8. FloorPlanCAD and CAD graph methods

- **FloorPlanCAD** ([site](https://floorplancad.github.io/)):
  - 15,663 CAD floor plans (November 2021 release) in SVG, with line-grained annotations plus PNG renders and COCO visualisations.
  - Task: panoptic symbol spotting (countable "things" plus uncountable "stuff").
  - **License:** annotations and website are **CC BY-NC 4.0**, and the authors "do not own the copyright of the drawings".
  - The project was shut down in early 2022.
  - **The data is non-commercial. We cannot use it to train commercial production models without separate rights.** Research and benchmarking only.
- **GAT-CADNet** (CVPR 2022, [arXiv 2201.00625](https://arxiv.org/abs/2201.00625)):
  - Each drawing is a graph of primitives. A GAT branch predicts semantic labels, and instances are found as subgraphs by predicting the adjacency matrix.
  - It adds Relative Spatial Encoding and Cascaded Edge Encoding modules.
  - The PQ of 0.737 comes from a secondary summary (Not verified in the paper).
  - Official code license: Not verified.
- **CADTransformer** (CVPR 2022 oral, [repo](https://github.com/VITA-Group/CADTransformer), **MIT**): a transformer over primitive embeddings with an HRNet-W48 input embedding, trained on FloorPlanCAD.

## 9. License verification

| Item | Finding | Source |
|---|---|---|
| (a) SegFormer, official NVIDIA code and checkpoints | "NVIDIA Source Code License for SegFormer", §3.3: "only may be used or intended for use non-commercially", meaning "research or evaluation purposes only". The HF cards (e.g. `nvidia/segformer-b0-finetuned-ade-512-512`) list license "other" and link this file. **Non-commercial: confirmed.** The license text does not name weights explicitly, but NVIDIA's model cards apply it to them. | [LICENSE](https://github.com/NVlabs/SegFormer/blob/master/LICENSE), [HF card](https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512) |
| (b) SAM 2 | The README says the model checkpoints, demo code and training code are **Apache 2.0**. Demo fonts use SIL OFL 1.1. The cc_torch-derived connected-components code has its own `LICENSE_cctorch`, and the repo sidebar also shows BSD-3-Clause (which file it covers is Not verified). | [sam2 repo](https://github.com/facebookresearch/sam2) |
| (c) torchvision pretrained weights | "The pre-trained models provided in this library may have their own licenses or terms and conditions derived from the dataset used for training. It is your responsibility to determine whether you have permission to use the models for your use case." The torchvision BSD-3 code license does not automatically cover the weights. | [torchvision models](https://docs.pytorch.org/vision/stable/models.html) |
| (d) Mask2Former / Detectron2 | Mask2Former: "majority ... MIT". Swin-Transformer-Semantic-Segmentation parts are MIT and Deformable-DETR parts are Apache-2.0. The repo was **archived Jan 1, 2025**. Detectron2: **Apache 2.0**. Model-zoo weight licenses are not stated separately (Not verified). Pretrained backbones inherit dataset terms (ImageNet, COCO). | [Mask2Former](https://github.com/facebookresearch/Mask2Former), [Detectron2](https://github.com/facebookresearch/detectron2) |
| (e) RT-DETR (lyuwenyu) | Repo is **Apache-2.0**. No separate weights license is stated (Not verified). | [RT-DETR](https://github.com/lyuwenyu/RT-DETR) |
| FloorPlanCAD | CC BY-NC 4.0; drawing copyright not held by the authors | [site](https://floorplancad.github.io/) |

---

## 10. Recommendation for Kentucky AI

| Area | Pattern to adopt | Why |
|---|---|---|
| Dataset management | Immutable **dataset versions** with a recorded split, preprocessing and augmentation recipe (Roboflow-style), validated server-side before READY (Fireworks-style) | Reproducible training; every model traces back to an exact snapshot |
| Job lifecycle | Our own explicit state machine with terminal-state immutability, an `estimatedCost` field and GPU-second metering | Fireworks and HF Jobs both expose rich job states and metering; ours must support billing customers |
| Annotation ↔ model coupling | Label Studio OSS **ML backend** (`predict` / `fit`) plus webhooks, deployed as a separate service (CVAT/Nuclio-style) | Open source (Apache-2.0), already in our fork, and keeps GPU serving decoupled |
| Active learning, agreement, review | **Build our own** on OSS primitives (predictions, webhooks, task sorting) | These are Enterprise-only in Label Studio; we must not copy or imply Enterprise code |
| Burst GPU training | Modal (`spawn` → `FunctionCall.get(timeout=0)` polling, Volumes for artifacts) for jobs under 24 h with checkpoint and resume | Per-second billing and simple async API. **Blocker:** confirm the Terms permit customer-facing use before production |
| Long or large training | Lambda Cloud on-demand instances launched with `user_data` cloud-init, using **base URL `https://cloud.lambda.com/api/v1` and Bearer auth** | No 24 h cap; cloud-init lets an instance bootstrap itself; the `cloud.lambda.ai` host is deprecated |
| LLM fine-tuning | Fireworks Training API only if we add LLM or VLM features (e.g. spec-text extraction) | Not applicable to segmentation or GNN; managed SFT no longer accepts new jobs |
| Drawing segmentation models | Prefer Apache/MIT-licensed code: Mask2Former (MIT, archived) or Detectron2 (Apache), RT-DETR (Apache), SAM 2 (Apache) | Commercial use allowed by the code licenses, but each pretrained weight's dataset terms still need checking |
| Avoid in production | NVIDIA SegFormer official weights and code; FloorPlanCAD-trained weights | Non-commercial licenses (NVIDIA SCL §3.3; CC BY-NC 4.0) |
| Vector/CAD understanding | PyG `HeteroData` (primitive, text and symbol node types) + `LinkNeighborLoader` / edge classification, informed by GAT-CADNet and CADTransformer | Matches line-grained CAD structure; train on our own licensed data |

## Sources

- https://docs.roboflow.com/datasets/dataset-versions
- https://docs.roboflow.com/guides/model-training.md
- https://huggingface.co/docs/autotrain/index
- https://huggingface.co/docs/huggingface_hub/guides/jobs
- https://docs.cvat.ai/docs/administration/advanced/installation_automatic_annotation/
- https://docs.cvat.ai/docs/manual/advanced/serverless-tutorial/
- https://github.com/HumanSignal/label-studio-ml-backend
- https://labelstud.io/guide/ml
- https://labelstud.io/guide/webhook_reference
- https://labelstud.io/guide/label_studio_compare
- https://docs.humansignal.com/guide/release_notes/onprem/2.25.0.html
- https://modal.com/docs/reference/modal.Function
- https://modal.com/docs/reference/modal.FunctionCall
- https://modal.com/docs/reference/modal.Volume
- https://modal.com/docs/guide/job-queue
- https://modal.com/docs/guide/timeouts
- https://modal.com/pricing
- https://modal.com/legal/terms
- https://docs.lambda.com/api/cloud
- https://docs.lambda.com/api/cloud/spec.json
- https://pytorch-geometric.readthedocs.io/en/latest/notes/heterogeneous.html
- https://pytorch-geometric.readthedocs.io/en/latest/advanced/batching.html
- https://pytorch-geometric.readthedocs.io/en/latest/modules/loader.html
- https://floorplancad.github.io/
- https://arxiv.org/abs/2201.00625
- https://github.com/VITA-Group/CADTransformer
- https://github.com/NVlabs/SegFormer/blob/master/LICENSE
- https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512
- https://github.com/facebookresearch/sam2
- https://docs.pytorch.org/vision/stable/models.html
- https://github.com/facebookresearch/Mask2Former
- https://github.com/facebookresearch/detectron2
- https://github.com/lyuwenyu/RT-DETR
