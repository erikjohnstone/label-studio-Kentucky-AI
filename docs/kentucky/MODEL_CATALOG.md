# Model Catalog

Source of truth: `label_studio/kentucky/catalog.py` (served at `GET /api/ka/catalog/`, UI `/ka/catalog/`).
Only these approved templates can be trained; customers cannot submit code.

## A. Kentucky AI models
**None offered.** The audit of the available repositories found no Kentucky AI checkpoints
(OpenTakeoff Premium contains gradient-boosted tree JSON models and references private SAM weights
stored elsewhere). When Kentucky AI checkpoints exist, register them and they appear under
`kentucky_models`.

## B. Open architectures and pretrained base models

| id | Task | Architecture | Code license | Inits | CPU-trainable |
|---|---|---|---|---|---|
| **seg-dinov2-s** | semantic seg | DINOv2-with-registers ViT-S/14 (Meta) + multi-layer fusion head + full-resolution line branch | Apache-2.0 | **pretrained `facebook/dinov2-with-registers-small` @ `0d9846e` (Apache-2.0 weights → deployable)**; scratch | yes (GPU better) |
| seg-lraspp-mbv3 | semantic seg | torchvision LR-ASPP MobileNetV3-Large | BSD-3-Clause | scratch; torchvision COCO-VOC (**review required → not deployable**) | yes |
| seg-segformer-b0 | semantic seg | HF Transformers SegFormer (mit-b0 sized config) | Apache-2.0 | scratch only — NVIDIA checkpoints excluded (non-commercial license) | yes |
| **det-rtdetrv2-r18** | items (boxes) | RT-DETRv2 ResNet-18-vd, 300 queries; outline = box | Apache-2.0 | **pretrained `PekingU/rtdetr_v2_r18vd` @ `5650961` (Apache-2.0 weights, COCO → deployable)**; scratch | yes (GPU better) |
| **det-dfine-s** | items (boxes) | D-FINE-S (HGNetV2-S, fine-grained box refinement); outline = box | Apache-2.0 | **pretrained `ustc-community/dfine-small-coco` @ `f79e65b` (Apache-2.0, COCO → deployable)**; scratch | yes (GPU better) |
| det-rfdetr-s | items (boxes) | RF-DETR-S (DINOv2-S windowed backbone + LW-DETR decoder); outline = box; experimental | Apache-2.0 | **pretrained `Roboflow/rf-detr-small` @ `3bdc465` (Apache-2.0, COCO → deployable)**; scratch | yes (GPU better) |
| inst-maskrcnn-mbv3 | instance seg | torchvision Mask R-CNN + MobileNetV3-FPN (GroupNorm) | BSD-3-Clause | scratch | yes (slow) |
| inst-maskrcnn-r50-v2 | instance seg | torchvision Mask R-CNN ResNet-50-FPN v2 | BSD-3-Clause | scratch; COCO (**review required**) | no (GPU) |
| **gnn-gps-node** | node cls | PyG GPSConv(GINEConv, 4 heads) ×3 graph transformer | MIT | scratch | yes |
| gnn-sage-node | node cls | PyG SAGEConv ×3 + MLP | MIT | scratch | yes |
| gnn-gat-node | node cls | PyG GATv2Conv(edge_dim) ×3 + MLP | MIT | scratch | yes |
| gnn-gcn-node | node cls | PyG GCNConv ×3 + MLP | MIT | scratch | yes |
| gnn-sage-edge | relation cls | SAGE encoder + MLP([h_u, h_v, \|h_u−h_v\|, e]) | MIT | scratch | yes |

## C. From scratch / from your checkpoint
* `scratch`: new weights; needs much more labeled data and compute than fine-tuning.
* `checkpoint`: fine-tune or continue from one of **your** registered versions of the same
  architecture; incompatible heads (class count changes) are re-initialized and logged.

## License record per init
`checkpoint_license`, `commercial_use`, `commercially_deployable`, `fine_tuning_allowed`,
`redistribution`, `hosting_restrictions`, `attribution`, `revision`, `checksum`, `source`.
Weights are never assumed to share the framework's license. A model trained from an init that is not
cleared is registered with `commercially_deployable: false` and **cannot be deployed**; an operator can
clear specific inits with `KA_CLEARED_CHECKPOINTS = ['seg-lraspp-mbv3:pretrained']` after legal review.
Checksums of downloaded torchvision weights are recorded from the hash-suffixed filename at download
time (not pre-filled).

## Assisted labeling
SAM 2 (code and weights Apache-2.0 per Meta's repository) is listed as an integration point for mask
proposals; weights are not bundled. Verify the current license before enabling
(`docs/kentucky/research/ML_PLATFORM_RESEARCH.md`).

## Choosing base models (research)
`docs/kentucky/research/BASE_MODELS.md` compares task-specific candidates with code, weights and training-data
licenses checked separately. Added from it: DINOv2-S (outline areas), RT-DETRv2-R18, D-FINE-S and RF-DETR-S (items), and the GPS + GINE graph
transformer (line-by-line); measured results in TEST_RESULTS.md. Next candidates: RF-DETR-Seg (item masks; its
transformers port is detection-only today), docTR (drawing text), SAM 2.1 + Grounding DINO (assisted labeling).
RF-DETR sizes above base and DEIMv2's DINOv3 variants (DINOv3 license) are excluded. Excluded for license reasons: Mask2Former weights, NVIDIA
SegFormer, Ultralytics YOLO, any model trained on FloorPlanCAD / ArchCAD-400K / CubiCasa5k (all CC BY-NC).
No commercially usable floor-plan-pretrained checkpoint exists publicly: a Kentucky AI base model trained on
permissive data (e.g. Modified Swiss Dwellings, CC BY 4.0) would fill that gap.
