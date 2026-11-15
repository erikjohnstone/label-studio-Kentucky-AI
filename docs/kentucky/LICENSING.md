# Licensing

| Component | License | Use |
|---|---|---|
| Label Studio (this fork) | Apache-2.0 | Base application; NOTICE/LICENSE preserved |
| Kentucky platform code (`label_studio/kentucky`, `docs/kentucky`, `deploy/modal`) | Apache-2.0 (inherits repo license unless Kentucky AI decides otherwise) | New code; no proprietary Premium source copied |
| OpenTakeoff Premium | Proprietary (all rights reserved), AGPL portions after the Apache cutoff | Inspected only; design token **values** reproduced; no source, logo artwork or customer data copied |
| pdfplumber / pdfminer.six | MIT | Vector + text extraction |
| pypdfium2 / PDFium | Apache-2.0 / BSD-3-Clause | PDF rendering |
| ezdxf | MIT | DXF parsing |
| OpenCV (headless) | Apache-2.0 | Raster vectorization |
| RapidOCR (onnxruntime) | Apache-2.0 | OCR on scans |
| Shapely | BSD-3-Clause | Geometry |
| PyTorch / torchvision | BSD-3-Clause | Training |
| PyTorch Geometric | MIT | GNNs |
| Hugging Face Transformers | Apache-2.0 | SegFormer architecture (scratch init) |
| PyMuPDF | AGPL-3.0 | **Not used** (deliberately avoided) |

## Model weights
Weights are licensed separately from frameworks (see `MODEL_CATALOG.md`):
* NVIDIA SegFormer checkpoints — excluded (NVIDIA Source Code License, non-commercial).
* torchvision COCO-trained checkpoints — usable for evaluation; marked *review required* and not
  deployable until cleared by counsel.
* Models trained from scratch on customer data — customer-owned weights, deployable.
* SAM 2 — Apache-2.0 per Meta's repository (integration point only; verify before enabling).

Research notes with sources: `research/ML_PLATFORM_RESEARCH.md`.
