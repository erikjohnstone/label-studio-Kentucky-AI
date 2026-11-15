# Base model review — 7 research tracks (Nov 2026)

Question: are the models on the platform the best open-weight, commercially permissible starting points, per the
academic literature, for what customers train here (areas, item counts, linear MEP runs, vector line labeling, text)?
Answer: partly. Several are right; some should be demoted or replaced; important pieces are missing. Licenses were
checked against primary sources (LICENSE files, model cards). Items marked (inference) are judgement, not measured.

## Verdict on the current 13
| Plain name | Model | Verdict | Why |
|---|---|---|---|
| Smart area marker | DINOv2-S + U-Net decoder | **Keep (default)** | Strongest clean features with few labels. Add a high-res stem so 1–3 px lines survive, and a thin-line loss (Tversky / clDice) |
| Quick area marker | LR-ASPP from zero | Demote | Coarse 1/8 output, no pretraining: poor on thin lines with few labels |
| Large-scale area marker | SegFormer from zero | Replace / demote | Needs lots of data from zero; 2025 wall-segmentation work reports blurred boundaries |
| Adaptive item counter | RF-DETR-S | **Keep (default)** | Best detector in the 2026 AEC drawing benchmark (mAP50 0.949); hard-block the non-Apache sizes |
| Precise item counter | D-FINE-S (COCO) | Keep | Ties RF-DETR on RF100-VL, lighter; ship COCO (not Objects365) weights |
| All-around item counter | RT-DETRv2 | Demote | Superseded by D-FINE / DEIM in the same lineage |
| Shape-tracing counter | Mask R-CNN MBv3 from zero | Replace | From zero does poorly on small sets; counting needs boxes, not masks |
| Large shape-tracing counter | Mask R-CNN R50 | Unblock if legal agrees | Blocking torchvision COCO weights is inconsistent with allowing COCO-trained DETRs |
| Long-run line labeler | GPS graph transformer | **Keep (default)** | Long-range attention matters on CAD (all SOTA uses it); add edge attributes + geometric attention bias |
| Symbol-aware line labeler | GATv2 | Keep | GAT-CADNet analogue; use edge attributes |
| Fast line labeler | GraphSAGE | Demote to fast baseline | |
| Basic line labeler | GCN | Remove | No edge features; weakest |
| Line connector | GraphSAGE edge classifier | Replace | Use an edge-attribute MLP on the main model's embeddings (GAT-CADNet-style grouping) |

## Missing (ranked by impact)
1. **Tiling / sliced inference** for every detector (sheets are 5–14k px; symbols tiny). SAHI is MIT.
2. **Layer, linetype (dash), lineweight, block/INSERT name and text as graph features.** Layer ID is the single biggest
   feature on FloorPlanCAD (VecFormer ablation 88.4 → 91.1 PQ). Our PDF extraction currently drops dash patterns.
3. **Takeoff geometry layer** (not a model): snap endpoints, merge collinear segments, crossings vs junctions, scale
   from notes/dimensions, run length per system, fittings from node degree/angle.
4. **Scans → runs:** topology-aware loss (clDice MIT, Skeleton Recall Apache) + skeleton → graph (sknw BSD-3), and/or a
   line-segment detector (DeepLSD MIT) feeding the same GNN path as vectors.
5. **Segment-token transformer (VecFormer-style, Apache code / Pointcept MIT)** — the CAD state of the art (88–91 PQ);
   trained from scratch; overtakes GNNs once a customer has hundreds of labeled sheets (inference). GPU.
6. **Box-only CNN detector** for CPU/small sets: RTMDet or YOLOX (Apache) or MultimediaTechLab YOLOv9 (MIT); DEIM (v1, Apache) recipe for D-FINE.
7. **ConvNeXt/ResNet + U-Net(++)** area model (MIT/Apache) — the family that won 2025 wall-segmentation benchmarks; CPU-trainable.
8. **Text model:** PP-OCRv6 (Apache) or docTR (Apache) default, fine-tunable on customer tags/fonts; regex grammars for scale and sizes on vector PDFs.
9. **Labeling accelerators (GPU):** SAM 2.1 click-to-outline (Apache), OWLv2 image-guided "find all like this" (Apache), Florence-2 (MIT) for drawing text.
   No model has published zero-shot results on construction symbols; one benchmark found multimodal models ~40–55% on door/window counts.

## Exclude (license)
DEIMv2 (no commercial use incl. SaaS) · RF-DETR Atto/Femto/Pico/XL/2XL (Roboflow PML) · YOLOv6, Gold-YOLO, original YOLOv9 (GPL) ·
Ultralytics incl. YOLO-World port (AGPL) · SymPoint (non-commercial), SymPoint-V2 / CADSpotting / GAT-CADNet unofficial (no license) ·
DPSS/ArchCAD code (academic only) · PTv3 standalone `main` (CC BY-NC since 2026-10-30; use Pointcept MIT or pinned legacy) ·
NVIDIA SegFormer/MiT and RADIO code · Hiera standalone weights · XRay-/Cell-DINO · Surya weights (revenue cap + competitor ban) ·
Qwen2.5-VL-3B (research license) · T-Rex2 / Rex-Omni (non-commercial) · Grounding DINO 1.5/1.6, DINO-X (API only, third-party in China) ·
HEAT (no commercial) · Deep Hough Transform, RNGDet++ (no license) · LayoutLMv3 (NC) · PyMuPDF (AGPL; not used here — verified).
**Legal review first:** DINOv3, SAM 3, C-RADIOv4 (military/ITAR/nuclear bans, attribution), Gemma/PaliGemma terms, CC BY-SA data (PID2Graph).

## Datasets (for a Kentucky AI base model)
Usable (attribution): Swiss Dwellings (CC BY 4.0, 42k apartments), Modified Swiss Dwellings (CC BY 4.0), Floor Plan CIS (CC BY 4.0),
HABS/HAER/HALS measured drawings (public domain), DocLayNet (CDLA-Permissive), CGHD circuits (CC BY / CC0).
Risky: ResPlan (scraped listings), PID2Graph (CC BY-SA). Excluded: CubiCasa5k, FloorPlanCAD, ArchCAD-400K, ZInD, Structured3D, CVC-FP, RPLAN, R2V.
No commercially usable drawing-pretrained checkpoint exists for any task. Permit drawings are copyrighted (counsel); pooling customer labels needs contract terms.

## Key sources
VecFormer arxiv.org/abs/2505.23395 · GAT-CADNet arxiv.org/abs/2201.00625 · AEC layout detection arxiv.org/abs/2607.18997 ·
AECV-Bench arxiv.org/abs/2601.04819 · MitUNet arxiv.org/abs/2512.02413 · RF100-VL rfdetr.roboflow.com/develop/learn/benchmarks ·
PID2Graph arxiv.org/abs/2411.13929 · DEIMv2 LICENSE github.com/Intellindust-AI-Lab/DEIMv2 · PTv3 NOTICE github.com/Pointcept/PointTransformerV3 ·
Surya MODEL_LICENSE github.com/datalab-to/surya · Rezvanifar et al. arxiv.org/abs/2006.00684 · Schönfelder et al. doi:10.1016/j.autcon.2023.105156
