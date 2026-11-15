"""Model catalog: approved training templates with per-model license records.

Rules enforced here (and in ``validate_selection``):
* Implementation (code) license and checkpoint (weights) license are recorded separately.
* An init option whose checkpoint is not cleared for commercial use is marked
  ``commercially_deployable: False``: it can be used for internal evaluation, but a model trained
  from it cannot be deployed until the checkpoint is cleared (``KA_CLEARED_CHECKPOINTS``).
* Only approved templates run; customers cannot upload executable training code.

Kentucky AI pretrained models: the repository audit (docs/kentucky/LABEL_STUDIO_AUDIT.md, code-reuse
map) found NO Kentucky AI checkpoints in the available repositories, so none are listed. When
Kentucky AI checkpoints are published to the registry with ``organization=None``-equivalent
platform scope, they appear under ``source: kentucky``.
"""

from __future__ import annotations

from django.conf import settings

TORCHVISION = {'implementation': 'torchvision', 'implementation_license': 'BSD-3-Clause',
               'source': 'https://github.com/pytorch/vision'}
PYG = {'implementation': 'PyTorch Geometric', 'implementation_license': 'MIT', 'source': 'https://github.com/pyg-team/pytorch_geometric'}
HF = {'implementation': 'Hugging Face Transformers', 'implementation_license': 'Apache-2.0',
      'source': 'https://github.com/huggingface/transformers'}

SCRATCH = {
    'id': 'scratch', 'label': 'Random initialization (train from scratch)', 'checkpoint_license': 'n/a (new weights)',
    'commercial_use': True, 'commercially_deployable': True, 'fine_tuning_allowed': True, 'redistribution': 'customer-owned weights',
    'hosting_restrictions': 'none', 'attribution': 'none', 'checksum': None, 'revision': None,
    'note': 'Requires substantially more labeled data and compute than fine-tuning.',
}

CATALOG = [
    {
        'id': 'seg-lraspp-mbv3', 'task': 'semantic_segmentation', 'family': 'cv', 'name': 'LR-ASPP MobileNetV3-Large',
        'architecture': 'torchvision.models.segmentation.lraspp_mobilenet_v3_large', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': 'Fast, lightweight model for outline areas (walls, rooms, slabs, finish areas). MobileNetV3 + LR-ASPP was designed for mobile devices (Howard et al., 2019): it trains in minutes on a CPU and is cheap to run, but its coarse output can soften very thin lines and small details. Use it for a quick first model, for bold high-contrast areas, or when you retrain often. Works on scans and vector PDFs. Starts from zero (deployable); the torchvision COCO start needs a license review.',
        'gpu_recommended': 'none (CPU ok) / T4', 'badge': 'Fastest', 'cpu_trainable': True,
        'inits': [SCRATCH, {
            'id': 'pretrained', 'label': 'torchvision COCO (VOC labels) checkpoint',
            'weights_enum': 'LRASPP_MobileNet_V3_Large_Weights.COCO_WITH_VOC_LABELS_V1',
            'checkpoint_license': 'Distributed with torchvision (BSD-3-Clause); trained on COCO images whose licenses vary (Flickr terms)',
            'commercial_use': 'review_required', 'commercially_deployable': False, 'fine_tuning_allowed': True,
            'redistribution': 'review_required', 'hosting_restrictions': 'review_required',
            'attribution': 'torchvision, COCO', 'checksum': None, 'revision': 'v1',  # recorded from the hash-suffixed torchvision filename at download time
            'note': 'Downloaded from download.pytorch.org at train time; legal review pending, therefore not deployable.',
        }],
    },
    {
        'id': 'seg-dinov2-s', 'task': 'semantic_segmentation', 'family': 'cv', 'name': 'DINOv2-S segmentation (pretrained)',
        'architecture': 'transformers.Dinov2WithRegistersModel (ViT-S/14, 4 registers) + multi-layer fusion head with a full-resolution line branch',
        **HF, 'version': 'transformers>=4.48',
        'description': "Outline areas when you have few labeled sheets or very mixed drawings. Meta's DINOv2 (Oquab et al., 2023) learned general-purpose image features from 142M images without labels; the paper shows those features segment well with little task-specific training. That makes it a strong choice for scans of varying quality, hand-marked sets and unusual drawing styles. Slower and larger than LR-ASPP; GPU recommended. Apache-2.0 weights, deployable.",
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True, 'badge': 'Best with few labels', 'best_for': 'scan', 'min_sheets': 5,
        'inits': [{
            'id': 'pretrained', 'label': 'DINOv2-with-registers-small (Meta, Apache-2.0)', 'hf_id': 'facebook/dinov2-with-registers-small',
            'checkpoint_license': 'Apache-2.0 (model card + LICENSE)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'Meta AI, DINOv2 (Apache-2.0)', 'checksum': None, 'revision': '0d9846e56b43a21fa46d7f3f5070f0506a5795a9',
            'source': 'https://huggingface.co/facebook/dinov2-with-registers-small',
            'note': 'Pinned to an exact Hugging Face revision; downloaded at train time. Pretraining data (LVD-142M) is not redistributed.',
        }, SCRATCH],
    },
    {
        'id': 'seg-segformer-b0', 'task': 'semantic_segmentation', 'family': 'cv', 'name': 'SegFormer-B0 (architecture)',
        'architecture': 'transformers.SegformerForSemanticSegmentation (mit-b0 config)', **HF, 'version': 'transformers>=4.40',
        'description': "Outline areas once you have a large labeled set (thousands of sheets). SegFormer (Xie et al., 2021) uses a hierarchical transformer with no fixed positional encoding, so it copes well with sheets of different sizes and scales. Here it can only start from zero: NVIDIA's pretrained weights are licensed for non-commercial research only, so they are excluded. Without pretraining it needs far more data than DINOv2 or LR-ASPP.",
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True,
        'inits': [SCRATCH],
        'excluded_checkpoints': [{'id': 'nvidia/mit-b0', 'reason': 'NVIDIA Source Code License - non-commercial'}],
    },
    {
        'id': 'det-dfine-s', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'D-FINE-S (pretrained)',
        'architecture': 'transformers.DFineForObjectDetection (HGNetV2-S backbone, fine-grained box refinement); outlines are boxes',
        **HF, 'version': 'transformers>=4.52',
        'description': 'Counting items where exact position matters: doors, fixtures, devices, diffusers, small symbols. D-FINE (Peng et al., 2024) predicts each box edge as a refined probability distribution instead of a single number, which the paper shows gives more precise boxes than earlier real-time detectors, especially for small objects. Small (10M parameters), fast to train. Gives a box per item, not an exact outline. Apache-2.0 weights, deployable.',
        'gpu_recommended': 'T4 / A10G (CPU ok for small sets)', 'cpu_trainable': True, 'badge': 'Most precise boxes', 'best_for': 'scan',
        'inits': [{
            'id': 'pretrained', 'label': 'D-FINE-S COCO (ustc-community, Apache-2.0)', 'hf_id': 'ustc-community/dfine-small-coco',
            'checkpoint_license': 'Apache-2.0 (model card)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'D-FINE authors (Apache-2.0); COCO-only pretraining (the Objects365 variants are excluded pending review)',
            'checksum': None, 'revision': 'f79e65b5fbb33ceb9d3ebba042955d7410c608f8', 'source': 'https://huggingface.co/ustc-community/dfine-small-coco',
            'note': 'Pinned revision; config vendored in training/configs.',
        }, SCRATCH],
    },
    {
        'id': 'det-rfdetr-s', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'RF-DETR-S (pretrained)',
        'architecture': 'transformers.RfDetrForObjectDetection (DINOv2-S windowed backbone, LW-DETR decoder); outlines are boxes',
        **HF, 'version': 'transformers>=5.8',
        'description': 'Counting items on drawings that look nothing like photographs. RF-DETR (Roboflow, 2025) pairs a DINOv2 backbone with a lightweight DETR decoder and was built and tested for transfer to new domains: it leads the RF100-VL benchmark of 100 varied datasets (aerial, medical, documents, industrial). Good for unusual symbol libraries and mixed scan quality. Larger and more memory-hungry than D-FINE; GPU recommended. Small size is Apache-2.0, deployable (the XL / 2XL detection sizes use a different license and are not offered).',
        'gpu_recommended': 'T4 / A10G', 'badge': 'Built for new domains', 'cpu_trainable': True, 'experimental': True,
        'inits': [{
            'id': 'pretrained', 'label': 'RF-DETR-S COCO (Roboflow, Apache-2.0)', 'hf_id': 'Roboflow/rf-detr-small',
            'checkpoint_license': 'Apache-2.0 (model card)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'Roboflow RF-DETR (Apache-2.0 for nano/small/medium/base; the larger sizes and RF-DETR+ use other '
                           'licenses and are excluded); DINOv2 backbone by Meta (Apache-2.0)',
            'checksum': None, 'revision': '3bdc465063270f99769da5a1b4c00c68bd2d439d', 'source': 'https://huggingface.co/Roboflow/rf-detr-small',
            'note': 'Pinned revision; config vendored in training/configs.',
        }, SCRATCH],
    },
    {
        'id': 'det-rtdetrv2-r18', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'RT-DETRv2 R18 (pretrained)',
        'architecture': 'transformers.RTDetrV2ForObjectDetection (ResNet-18-vd, 300 queries); outlines are boxes', **HF, 'version': 'transformers>=4.49',
        'description': 'General-purpose item counter and a dependable default. RT-DETRv2 (Lv et al., 2024) is the improved version of RT-DETR, the first real-time end-to-end detection transformer: no anchor boxes or duplicate-removal step, with training refinements for flexible deployment. Well supported and fast to run. Gives a box per item, not an exact outline. Apache-2.0 weights, deployable.',
        'gpu_recommended': 'T4 / A10G (CPU ok for small sets)', 'cpu_trainable': True, 'badge': 'Dependable default', 'best_for': 'vector',
        'inits': [{
            'id': 'pretrained', 'label': 'RT-DETRv2-R18 COCO (PekingU, Apache-2.0)', 'hf_id': 'PekingU/rtdetr_v2_r18vd',
            'checkpoint_license': 'Apache-2.0 (model card)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'RT-DETRv2 authors (Apache-2.0); COCO-pretrained like the torchvision models', 'checksum': None,
            'revision': '5650961749fa93567c0d46fc7f43ea4f9e914107', 'source': 'https://huggingface.co/PekingU/rtdetr_v2_r18vd',
            'note': 'Pinned revision; config vendored in training/configs. COCO images carry mixed Flickr licenses — same basis as '
                    'other COCO-pretrained weights; weights license is Apache-2.0.',
        }, SCRATCH],
    },
    {
        'id': 'inst-maskrcnn-mbv3', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'Mask R-CNN MobileNetV3-FPN',
        'architecture': 'torchvision.models.detection.MaskRCNN + mobilenet_v3_large FPN backbone', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': "Counting items when you also need each item's true shape, not just a box: irregular equipment, fixtures, odd-shaped devices. Mask R-CNN (He et al., 2017) finds each item and then draws its pixel outline. This lightweight version starts from zero, so it needs more labeled sheets than the pretrained detectors before it is reliable. CPU-trainable on small sets.",
        'gpu_recommended': 'T4 / A10G', 'badge': 'Gives exact shapes', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'inst-maskrcnn-r50-v2', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'Mask R-CNN ResNet-50-FPN v2',
        'architecture': 'torchvision.models.detection.maskrcnn_resnet50_fpn_v2', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': 'Higher-capacity Mask R-CNN for item shapes on large labeled sets. Same idea as the MobileNet version (box plus pixel outline per item) with a stronger ResNet-50 backbone; needs a GPU. Can start from zero (deployable). torchvision\'s COCO weights are offered only after a license review: torchvision states its weights "may have their own licenses or terms and conditions derived from the dataset used for training".', 'gpu_recommended': 'A10G / A100', 'cpu_trainable': False,
        'inits': [SCRATCH, {
            'id': 'pretrained', 'label': 'torchvision COCO checkpoint', 'weights_enum': 'MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1',
            'checkpoint_license': 'Distributed with torchvision (BSD-3-Clause); COCO-trained', 'commercial_use': 'review_required',
            'commercially_deployable': False, 'fine_tuning_allowed': True, 'redistribution': 'review_required',
            'hosting_restrictions': 'review_required', 'attribution': 'torchvision, COCO', 'checksum': None, 'revision': 'COCO_V1',
            'note': 'Legal review pending.',
        }],
    },
    {
        'id': 'gnn-gps-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'Graph transformer (GPS + GINE)',
        'architecture': 'torch_geometric GPSConv(GINEConv with edge features, multi-head global attention) x3 + MLP', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Labels every line on vector PDFs and DXF by looking at the whole sheet. GPS (Rampasek et al., 2022) combines local message passing, between lines that touch, cross or run parallel, with global attention across all lines. That suits linear runs (duct, pipe, conduit), where a line's identity can depend on a tag or a piece of equipment far along the run. Needs vector drawings, not scans. Memory grows with sheet size, so very dense sheets may need a GPU.",
        'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH], 'badge': 'Sees the whole sheet', 'recommended': True,
    },
    {
        'id': 'gnn-sage-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'GraphSAGE node classifier',
        'architecture': 'torch_geometric.nn.SAGEConv x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Labels every line on vector PDFs and DXF, fast, even on very dense sheets. GraphSAGE (Hamilton et al., 2017) learns from each line's neighbourhood and generalises to drawings it has never seen, and it scales to large graphs. A good first line-by-line model and a fast fallback for huge sheets. Looks only at nearby lines, so it can miss context that comes from far along a run. Needs vector drawings.",
        'gpu_recommended': 'none (CPU ok)', 'badge': 'Fast on big sheets', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-gat-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'GATv2 node classifier (edge-aware)',
        'architecture': 'torch_geometric.nn.GATv2Conv(edge_dim) x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': 'Labels every line on vector PDFs and DXF, weighting which neighbours matter. GATv2 (Brody et al., 2022) uses attention to decide how much each connected line counts, and also reads how lines meet (touch, cross, parallel). Graph attention on CAD primitives is the approach of GAT-CADNet (CVPR 2022), which reported strong symbol spotting on CAD floor plans. Good for symbols and junctions. Needs vector drawings.',
        'gpu_recommended': 'none (CPU ok)', 'badge': 'Proven on CAD symbols', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-gcn-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'GCN node classifier',
        'architecture': 'torch_geometric.nn.GCNConv x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': 'Simplest line-by-line model: a reference point to compare the others against. GCN (Kipf & Welling, 2017) averages each line with its neighbours equally, which can blur labels where different systems meet (a duct crossing a pipe). Use it to check that a harder model is really earning its keep. Needs vector drawings.', 'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-sage-edge', 'task': 'edge_classification', 'family': 'gnn', 'name': 'GraphSAGE relation classifier',
        'architecture': 'SAGEConv encoder + MLP([h_u, h_v, |h_u-h_v|, edge_attr])', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Connects lines into whole objects and runs. Instead of naming each line, it predicts how two lines relate: same object, connected to, hosted by (a door in a wall), bounded by. That is what turns separate segments into one continuous duct, pipe or conduit run, so you can total its length, and groups a symbol's lines into one counted item. Built on GraphSAGE (Hamilton et al., 2017). Needs vector drawings.",
        'gpu_recommended': 'none (CPU ok)', 'badge': 'Joins runs & symbols', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
]

# Every catalog model can also be initialized from one of the organization's own registered model
# versions of the same catalog id ("checkpoint" init = fine-tuning / continued training).
CHECKPOINT_INIT = {
    'id': 'checkpoint', 'label': 'Your registered model version (fine-tune / resume)', 'checkpoint_license': 'customer-owned',
    'commercial_use': 'inherits', 'commercially_deployable': 'inherits', 'fine_tuning_allowed': True,
}

SEGMENTATION_ASSIST = [{
    'id': 'sam2', 'name': 'SAM 2 (Segment Anything 2)', 'implementation_license': 'Apache-2.0', 'checkpoint_license': 'Apache-2.0',
    'commercial_use': True, 'status': 'integration point - weights not bundled; enable with KA_SAM2_CHECKPOINT',
    'source': 'https://github.com/facebookresearch/sam2',
}]


def get(catalog_id: str) -> dict | None:
    return next((c for c in CATALOG if c['id'] == catalog_id), None)


def init_option(entry: dict, init_id: str) -> dict | None:
    if init_id == 'checkpoint':
        return CHECKPOINT_INIT
    return next((i for i in entry['inits'] if i['id'] == init_id), None)


def deployable(catalog_id: str, init_id: str, base_license: dict | None = None) -> tuple[bool, str]:
    entry = get(catalog_id)
    if entry is None:
        return False, 'unknown catalog model'
    opt = init_option(entry, init_id)
    if opt is None:
        return False, 'unknown init'
    if init_id == 'checkpoint':
        if base_license is None:
            return False, 'base checkpoint license unknown'
        return bool(base_license.get('commercially_deployable')), base_license.get('reason', 'inherited from base checkpoint')
    cleared = set(getattr(settings, 'KA_CLEARED_CHECKPOINTS', []) or [])
    if opt.get('commercially_deployable') is True or f'{catalog_id}:{init_id}' in cleared:
        return True, 'cleared'
    return False, f'checkpoint license {opt.get("commercial_use")}: not cleared for commercial deployment'


def public_catalog() -> dict:
    return {
        'kentucky_models': [],
        'kentucky_models_note': 'No Kentucky AI checkpoints were found in the audited repositories; none are offered.',
        'open_models': CATALOG,
        'checkpoint_init': CHECKPOINT_INIT,
        'segmentation_assist': SEGMENTATION_ASSIST,
    }
