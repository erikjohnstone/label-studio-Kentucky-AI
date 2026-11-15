# Base-model shortlist for a commercial construction-drawing training platform
Checked 2026-11-15 against HF model cards, GitHub LICENSE files and MODEL_ZOO docs. This is not legal advice; send REVIEW items to counsel.
Abbreviations: C = code license, W = weights license, D = training data. OK = COMMERCIAL-OK.

**Data caveat that applies throughout:** almost every ImageNet- or COCO-pretrained checkpoint, including the torchvision weights already in the catalog, inherits ImageNet's research-only terms and COCO's Flickr image terms. The industry treats these weights as usable under their weights license, and I follow that convention. ADE20K-trained heads are a step riskier ("non-commercial research/education" terms), so they get REVIEW.

## 1. Semantic segmentation (raster plans)
| Candidate | Checkpoint | C / W / D | Verdict | Params | HW | Plug-in |
|---|---|---|---|---|---|---|
| DINOv2 (+registers) backbone + UperNet/linear head | `facebook/dinov2-small`, `facebook/dinov2-with-registers-small` (also -base) | Apache-2.0 / Apache-2.0 / LVD-142M (Meta-curated) | **OK** ([card](https://hf.co/facebook/dinov2-small)) | 22M (S), 86M (B) | S: CPU possible at low res, B: GPU | `transformers.Dinov2Backbone` in `UperNetForSemanticSegmentation(backbone_config=...)`, or a custom head |
| ConvNeXt-V2 backbone + UperNet (head from scratch) | `facebook/convnextv2-tiny-22k-224` | Apache-2.0 / Apache-2.0 / IN-22k | **OK** ([card](https://hf.co/facebook/convnextv2-tiny-22k-224)) | 28M | GPU (T4) | `ConvNextV2Backbone` + `UperNetForSemanticSegmentation` |
| UperNet-ConvNeXt (full ADE20K model) | `openmmlab/upernet-convnext-tiny` | MIT / MIT / ADE20K | **REVIEW** (ADE20K terms) ([card](https://hf.co/openmmlab/upernet-convnext-tiny)) | 60M | GPU | `UperNetForSemanticSegmentation` |
| EoMT (encoder-only mask transformer on DINOv2) | `tue-mps/coco_panoptic_eomt_large_640` (COCO variants) | MIT / MIT / COCO | **OK**. ADE variants are REVIEW. ([card](https://hf.co/tue-mps/coco_panoptic_eomt_large_640)) | 317M (L) | GPU (A10G/A100) | `EomtForUniversalSegmentation` |
| DeepLabV3 / FCN ResNet-50 | torchvision `DeepLabV3_ResNet50_Weights.COCO_WITH_VOC_LABELS_V1` | BSD-3 / BSD-3 / COCO (VOC classes) | **OK** | 42M | GPU (CPU slow) | `torchvision.models.segmentation.deeplabv3_resnet50` |
| DINOv3 | `facebook/dinov3-vits16-pretrain-lvd1689m` (gated) | DINOv3 License / same / LVD-1689M | **REVIEW**: custom license, royalty-free and not NC, but has trade-control and termination clauses, must be passed on downstream, and is gated ([LICENSE](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md)) | 21.6M (S) | like DINOv2 | `AutoModel` / `DINOv3ViTModel` |
| Mask2Former (any facebook/* checkpoint) | `facebook/mask2former-swin-*` | MIT / **CC BY-NC 4.0** | **EXCLUDED** ([MODEL_ZOO](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md)). The architecture is fine: `Mask2FormerForUniversalSegmentation` with a DINOv2 or ConvNeXt backbone and the head trained from scratch. | | | |
| SegFormer / MiT | `nvidia/mit-b*`, `nvidia/segformer-*` | NVIDIA Source Code License (NC) | **EXCLUDED** | | | |
| Floor-plan checkpoints (e.g. `Yytsi/floorplan-to-3d-walls`) | various | tagged MIT/Apache, but D = CubiCasa5k (**CC BY-NC 4.0**) | **EXCLUDED** ([CubiCasa LICENSE](https://github.com/CubiCasa/CubiCasa5k)) | | | |

**Current catalog:** LR-ASPP MobileNetV3 stays as the CPU option. SegFormer-B0 trained from scratch is weaker than DINOv2-S with a light head, which is commercially clean. I found no floor-plan segmentation checkpoint whose training data is commercially clean. Modified Swiss Dwellings (CC BY 4.0, [4TU](https://doi.org/10.4121/e1d89cb5-6872-48fc-be63-aadd687ee6f9)) and the synthetic sets `benikm91/synthetic-floorplans-*` (CC BY 4.0) can be used to build an in-house domain-pretrained checkpoint.

## 2. Symbol detection / instance segmentation
| Candidate | Checkpoint | C / W / D | Verdict | Params | HW | Plug-in |
|---|---|---|---|---|---|---|
| RT-DETRv2 | `PekingU/rtdetr_v2_r18vd` (also r34/r50/r101) | Apache-2.0 / Apache-2.0 / COCO | **OK** ([card](https://hf.co/PekingU/rtdetr_v2_r18vd), [repo](https://github.com/lyuwenyu/RT-DETR)) | 20M (r18) | GPU (T4 OK) | `RTDetrV2ForObjectDetection` |
| D-FINE | `ustc-community/dfine-small-coco` (n/s/m/l/x) | Apache-2.0 / Apache-2.0 / COCO | **OK** ([card](https://hf.co/ustc-community/dfine-small-coco)). The `*-obj2coco` variants add Objects365: REVIEW the data terms. | 10M (S) | GPU; N/S fine-tune on CPU is slow but possible | `DFineForObjectDetection` |
| RF-DETR (Nano/Small/Medium/Large det; Seg N–2XL) | `rfdetr` pip, `RFDETRSmall`, `RFDETRSegSmall`, etc. | Apache-2.0 / Apache-2.0 (these sizes) / COCO, DINOv2 backbone | **OK** ([repo](https://github.com/roboflow/rf-detr)). Det XL/2XL and Atto/Femto/Pico are **PML 1.0 → EXCLUDED** without Roboflow Enterprise. | 30M (S) | GPU | `rfdetr` (PyTorch); not in transformers |
| DETR R-50 | `facebook/detr-resnet-50` | Apache-2.0 / Apache-2.0 / COCO | **OK** ([card](https://hf.co/facebook/detr-resnet-50)). Slow to converge and weak on small symbols. | 42M | GPU | `DetrForObjectDetection` |
| YOLOX | `yolox_s.pth` etc. ([repo](https://github.com/Megvii-BaseDetection/YOLOX)) | Apache-2.0 / Apache-2.0 / COCO | **OK** | 9M (S) | CPU-friendly (nano/tiny) | `yolox` package (plain PyTorch) |
| YOLO (MultimediaTechLab, v9/v7 reimplementation) | [repo](https://github.com/MultimediaTechLab/YOLO) | MIT / MIT (repo) / COCO | **REVIEW**: weights are ported from the GPL-3.0 originals | | | |
| Detectron2 model zoo | e.g. Mask R-CNN R50-FPN | Apache-2.0 / **CC BY-SA 3.0** | **REVIEW**: ShareAlike on fine-tuned weights ([MODEL_ZOO](https://github.com/facebookresearch/detectron2/blob/main/MODEL_ZOO.md)) | | | |
| YOLOv6 / v7 / v9 (originals) | | **GPL-3.0** | **EXCLUDED** | | | |
| Ultralytics YOLOv5/8/11 | | **AGPL-3.0** | **EXCLUDED** | | | |
| DEIMv2 | | custom non-commercial (2026) | **EXCLUDED** ([LICENSE](https://github.com/Intellindust-AI-Lab/DEIMv2/blob/main/LICENSE.md)). DEIM v1 is Apache-2.0 and OK. | | | |
| FloorPlanCAD-trained detectors (e.g. `joshlyman/rtdetrv2-floorplancad-doors`) | | tagged Apache, but D = FloorPlanCAD **CC BY-NC 4.0** | **EXCLUDED** | | | |

**Current catalog:** the torchvision Mask R-CNN (BSD-3, COCO) stays the instance-mask default. Add RT-DETRv2 or D-FINE for box-level symbol spotting, since they are much stronger on small dense symbols, and RF-DETR-Seg as the higher-accuracy mask option.

## 3. Vector / CAD graph learning
| Candidate | C / W / D | Verdict |
|---|---|---|
| FloorPlanCAD dataset | annotations **CC BY-NC 4.0**, and the drawings are not owned by the authors ([site](https://floorplancad.github.io)) | **EXCLUDED** for training shipped models. Note: Voxel51 HF mirrors are mis-tagged CC BY-SA. |
| ArchCAD-400K | **CC BY-NC 4.0**, gated ([HF](https://huggingface.co/datasets/jackluoluo/ArchCAD)) | **EXCLUDED** |
| CADTransformer | code **MIT** ([repo](https://github.com/VITA-Group/CADTransformer)); weights trained on FloorPlanCAD | Architecture OK, weights EXCLUDED |
| SymPoint | code and weights under IDEA "Non-commercial Scientific Research" license ([LICENSE](https://github.com/nicehuster/SymPoint)) | **EXCLUDED** |
| SymPoint-V2 | no LICENSE file found ([repo](https://github.com/nicehuster/SymPointV2)); weights on FloorPlanCAD | **EXCLUDED** |
| GAT-CADNet | no official code or weights | n/a (reimplement as a PyG `GATv2Conv` with edge attributes) |
| PyG GPS / GINE / GATv2 / TransformerConv / PointNet++ / PointTransformerConv | MIT ([PyG](https://github.com/pyg-team/pytorch_geometric)), no pretrained weights | **OK**, scratch training |
| Point Transformer V3 / Pointcept | MIT code; weights are 3D-scene (ScanNet etc.), not transferable | Architecture only |

**Finding:** no commercially licensed pretrained checkpoint exists for CAD primitive graphs. The catalog's scratch GraphSAGE/GATv2/GCN approach is correct. Two additions are worth making:
- `torch_geometric.nn.GPSConv` with `GINEConv` (local message passing plus global attention, edge features such as angle, length and parallelism). This approximates CADTransformer and GAT-CADNet and trains on CPU for small graphs.
- A raster-to-primitive feature hook: pool DINOv2-S patch features onto each primitive's bounding box as node features. This is how SymPoint-V2 and CADTransformer gain accuracy, and it remains clean if the image encoder is Apache-licensed.

Platform-owned self-supervised pretraining on customers' own DXF (masked-primitive prediction) is the only clean path to a "pretrained" graph model.

## 4. OCR on drawings
| Candidate | Checkpoint | C / W | Verdict | Size / HW | Plug-in |
|---|---|---|---|---|---|
| PP-OCRv5 det + rec | `PaddlePaddle/PP-OCRv5_mobile_det` / `_mobile_rec` (server variants for accuracy) | Apache-2.0 / Apache-2.0 | **OK** ([card](https://hf.co/PaddlePaddle/PP-OCRv5_mobile_rec), [repo](https://github.com/PaddlePaddle/PaddleOCR)) | mobile: few MB, CPU | PaddlePaddle; fine-tuning needs Paddle, not PyTorch |
| RapidOCR | ONNX/Torch ports of PP-OCR | Apache-2.0 / Apache-2.0 | **OK** ([repo](https://github.com/RapidAI/RapidOCR)) | CPU | inference only (ONNXRuntime/PyTorch) |
| docTR | `db_resnet50`, `fast_base`, `parseq`, `crnn_vgg16_bn`; `Felix92/doctr-torch-parseq-multilingual-v1` | Apache-2.0 / Apache-2.0 | **OK** ([repo](https://github.com/mindee/doctr), [card](https://hf.co/Felix92/doctr-torch-parseq-multilingual-v1)) | 20–25M, CPU-trainable recognizer | `doctr.models` (pure PyTorch): **best fit for the stack** |
| TrOCR | `microsoft/trocr-base-printed` (small: `trocr-small-printed`) | MIT (unilm) / no tag on the card, MIT per repo | **OK, light REVIEW** (card has no license tag) | 334M base, GPU | `VisionEncoderDecoderModel` |
| Florence-2 `<OCR_WITH_REGION>` | `microsoft/Florence-2-base` / `-large` | MIT / MIT | **OK** ([card](https://hf.co/microsoft/Florence-2-base)) | 0.23B / 0.77B, T4 | `AutoModelForCausalLM` (trust_remote_code; native in recent transformers) |
| Surya | | Apache-2.0 / modified OpenRAIL-M (revenue cap $5M) | **EXCLUDED** without a paid license ([README](https://github.com/VikParuchuri/surya)) | | |

Drawing-specific tip: use vector PDF text extraction first and run OCR only on rasters. Rotated dimension text needs a detector that supports angles (PP-OCR or docTR with `assume_straight_pages=False`).

## 5. Promptable / zero-shot assisted labeling
| Candidate | Checkpoint | C / W | Verdict | Size | Plug-in |
|---|---|---|---|---|---|
| SAM 2.1 | `facebook/sam2.1-hiera-tiny` / `-small` / `-base-plus` / `-large` | Apache-2.0 / Apache-2.0; D = SA-1B / SA-V | **OK** ([card](https://hf.co/facebook/sam2.1-hiera-small)) | 39M–224M | `Sam2Model` (transformers) or `sam2` pkg |
| Grounding DINO | `IDEA-Research/grounding-dino-tiny` / `-base` | Apache-2.0 / Apache-2.0; D = O365, GoldG, Cap4M mix | **OK** (data-mix note) ([card](https://hf.co/IDEA-Research/grounding-dino-base)) | 172M / 233M, GPU | `AutoModelForZeroShotObjectDetection` |
| OWLv2 | `google/owlv2-base-patch16-ensemble` | Apache-2.0 / Apache-2.0 | **OK**; image-conditioned "find more like this symbol" is ideal for symbols ([card](https://hf.co/google/owlv2-base-patch16-ensemble)) | 155M | `Owlv2ForObjectDetection.image_guided_detection` |
| Florence-2 | `microsoft/Florence-2-large` | MIT / MIT | **OK** | 0.77B | see §4 |
| Qwen3-VL | `Qwen/Qwen3-VL-4B-Instruct` (2B/8B also Apache) | Apache-2.0 / Apache-2.0 | **OK** ([card](https://hf.co/Qwen/Qwen3-VL-4B-Instruct)) | 4.4B, A10G/A100 (LoRA) | `AutoModelForImageTextToText` + PEFT |
| Qwen2.5-VL-7B | `Qwen/Qwen2.5-VL-7B-Instruct` | Apache-2.0 | **OK** | 8.3B | same |
| Qwen2.5-VL-3B / 72B | | **Qwen Research (NC)** / Qwen license | **EXCLUDED** / REVIEW ([LICENSE](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/blob/main/LICENSE)) | | |
| SAM 3 | `facebook/sam3` (gated) | SAM License (custom, royalty-free, trade-control and termination clauses) | **REVIEW** ([LICENSE](https://github.com/facebookresearch/sam3/blob/main/LICENSE)) | 860M | `Sam3Model` |

## Recommended catalog (COMMERCIAL-OK only)
| Task | Default | Alternatives |
|---|---|---|
| Semantic seg | **DINOv2-S/B (registers) + UperNet head** (`facebook/dinov2-with-registers-small`) | ConvNeXt-V2-T + UperNet (scratch head); EoMT-COCO for panoptic rooms; keep LR-ASPP MobileNetV3 for CPU |
| Symbol detection / instance | **RT-DETRv2-R18** (`PekingU/rtdetr_v2_r18vd`) for boxes; torchvision Mask R-CNN R50-FPN v2 for masks | D-FINE-S/M (COCO-only); RF-DETR-Seg Small/Medium (Apache sizes); YOLOX-Nano/S for CPU |
| CAD graph | **PyG GPSConv + GINEConv** (scratch) with DINOv2 patch features per primitive | GATv2 with edge attributes (GAT-CADNet-style); PointTransformerConv on primitive midpoints |
| OCR | **docTR** (`db_resnet50` + `parseq`) for in-stack PyTorch fine-tuning | PP-OCRv5 / RapidOCR (inference); Florence-2-base OCR-with-region |
| Assisted labeling | **SAM 2.1-small + Grounding DINO-base** (text→box→mask) | OWLv2 image-guided symbol search; Qwen3-VL-4B or Florence-2-large for captions and tags |

## Strong models excluded for license reasons
Mask2Former facebook/* weights (CC BY-NC); SegFormer / MiT (NVIDIA NC); Ultralytics YOLOv5–11 (AGPL); YOLOv6/v7/v9 originals (GPL-3.0); DEIMv2 (NC); RF-DETR XL/2XL det and Atto/Femto/Pico (PML 1.0); SymPoint / SymPoint-V2 (NC or no license); CADTransformer weights, any FloorPlanCAD- or ArchCAD-400K-trained model, and any CubiCasa5k-trained model (CC BY-NC data); Surya weights (OpenRAIL-M with revenue cap); Qwen2.5-VL-3B (research only).

**REVIEW:** DINOv3, SAM 3 (custom Meta licenses); Detectron2 zoo (CC BY-SA 3.0); ADE20K-trained heads; Objects365-pretrained variants; MultimediaTechLab YOLO weights.
