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
    'note': 'Starts knowing nothing. Needs many more labeled sheets to get good.',
}

CATALOG = [
    {
        'id': 'seg-lraspp-mbv3', 'plain_name': 'Quick area marker', 'task': 'semantic_segmentation', 'family': 'cv', 'name': 'LR-ASPP MobileNetV3-Large',
        'architecture': 'torchvision.models.segmentation.lraspp_mobilenet_v3_large', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': "Marks areas like rooms, walls and floors. Quick and cheap to train, so it's good for a first try. Can miss very thin lines.",
        'gpu_recommended': 'none (CPU ok) / T4', 'badge': 'Fastest', 'cpu_trainable': True,
        'inits': [SCRATCH, {
            'id': 'pretrained', 'label': 'torchvision COCO (VOC labels) checkpoint',
            'weights_enum': 'LRASPP_MobileNet_V3_Large_Weights.COCO_WITH_VOC_LABELS_V1',
            'checkpoint_license': 'Distributed with torchvision (BSD-3-Clause); trained on COCO images whose licenses vary (Flickr terms)',
            'commercial_use': 'review_required', 'commercially_deployable': False, 'fine_tuning_allowed': True,
            'redistribution': 'review_required', 'hosting_restrictions': 'review_required',
            'attribution': 'torchvision, COCO', 'checksum': None, 'revision': 'v1',  # recorded from the hash-suffixed torchvision filename at download time
            'note': "Starts from a model trained on everyday photos. Its license is still being checked, so models trained from it can't be put to use yet.",
        }],
    },
    {
        'id': 'seg-dinov2-s', 'plain_name': 'Smart area marker', 'task': 'semantic_segmentation', 'family': 'cv', 'name': 'DINOv2-S segmentation (pretrained)',
        'architecture': 'transformers.Dinov2WithRegistersModel (ViT-S/14, 4 registers) + multi-layer fusion head with a full-resolution line branch',
        **HF, 'version': 'transformers>=4.48',
        'description': "Marks areas like rooms, walls and floors. The best pick when you've only labeled a few sheets or your scans are messy. Takes longer to train.",
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True, 'badge': 'Fewest labels needed', 'best_for': 'scan', 'min_sheets': 5,
        'inits': [{
            'id': 'pretrained', 'label': 'DINOv2-with-registers-small (Meta, Apache-2.0)', 'hf_id': 'facebook/dinov2-with-registers-small',
            'checkpoint_license': 'Apache-2.0 (model card + LICENSE)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'Meta AI, DINOv2 (Apache-2.0)', 'checksum': None, 'revision': '0d9846e56b43a21fa46d7f3f5070f0506a5795a9',
            'source': 'https://huggingface.co/facebook/dinov2-with-registers-small',
            'note': 'Starts from a model that already understands images, so it learns from fewer labeled sheets.',
        }, SCRATCH],
    },
    {
        'id': 'seg-segformer-b0', 'plain_name': 'Large-scale area marker', 'task': 'semantic_segmentation', 'family': 'cv', 'name': 'SegFormer-B0 (architecture)',
        'architecture': 'transformers.SegformerForSemanticSegmentation (mit-b0 config)', **HF, 'version': 'transformers>=4.40',
        'description': 'Marks areas, but starts knowing nothing. Only worth it once you have thousands of labeled sheets.',
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True,
        'inits': [SCRATCH],
        'excluded_checkpoints': [{'id': 'nvidia/mit-b0', 'reason': 'NVIDIA Source Code License - non-commercial'}],
    },
    {
        'id': 'det-dfine-s', 'plain_name': 'Precise item counter', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'D-FINE-S (pretrained)',
        'architecture': 'transformers.DFineForObjectDetection (HGNetV2-S backbone, fine-grained box refinement); outlines are boxes',
        **HF, 'version': 'transformers>=4.52',
        'description': 'Finds and counts items like doors, fixtures and devices. Best with small symbols and at placing each one exactly.',
        'gpu_recommended': 'T4 / A10G (CPU ok for small sets)', 'cpu_trainable': True, 'badge': 'Most accurate placement', 'best_for': 'scan',
        'inits': [{
            'id': 'pretrained', 'label': 'D-FINE-S COCO (ustc-community, Apache-2.0)', 'hf_id': 'ustc-community/dfine-small-coco',
            'checkpoint_license': 'Apache-2.0 (model card)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'D-FINE authors (Apache-2.0); COCO-only pretraining (the Objects365 variants are excluded pending review)',
            'checksum': None, 'revision': 'f79e65b5fbb33ceb9d3ebba042955d7410c608f8', 'source': 'https://huggingface.co/ustc-community/dfine-small-coco',
            'note': 'Starts from a model already trained to find objects in photos, so it learns your symbols faster.',
        }, SCRATCH],
    },
    {
        'id': 'det-rfdetr-s', 'plain_name': 'Adaptive item counter', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'RF-DETR-S (pretrained)',
        'architecture': 'transformers.RfDetrForObjectDetection (DINOv2-S windowed backbone, LW-DETR decoder); outlines are boxes',
        **HF, 'version': 'transformers>=5.8',
        'description': 'Finds and counts items. Built to learn unfamiliar symbols quickly. Bigger and slower to train than D-FINE.',
        'gpu_recommended': 'T4 / A10G', 'badge': 'Learns new symbols fast', 'cpu_trainable': True, 'experimental': True,
        'inits': [{
            'id': 'pretrained', 'label': 'RF-DETR-S COCO (Roboflow, Apache-2.0)', 'hf_id': 'Roboflow/rf-detr-small',
            'checkpoint_license': 'Apache-2.0 (model card)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'Roboflow RF-DETR (Apache-2.0 for nano/small/medium/base; the larger sizes and RF-DETR+ use other '
                           'licenses and are excluded); DINOv2 backbone by Meta (Apache-2.0)',
            'checksum': None, 'revision': '3bdc465063270f99769da5a1b4c00c68bd2d439d', 'source': 'https://huggingface.co/Roboflow/rf-detr-small',
            'note': 'Starts from a model already trained to find objects in photos, so it learns your symbols faster.',
        }, SCRATCH],
    },
    {
        'id': 'det-rtdetrv2-r18', 'plain_name': 'All-around item counter', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'RT-DETRv2 R18 (pretrained)',
        'architecture': 'transformers.RTDetrV2ForObjectDetection (ResNet-18-vd, 300 queries); outlines are boxes', **HF, 'version': 'transformers>=4.49',
        'description': 'Finds and counts items. A solid all-around choice that runs fast.',
        'gpu_recommended': 'T4 / A10G (CPU ok for small sets)', 'cpu_trainable': True, 'badge': 'All-around', 'best_for': 'vector',
        'inits': [{
            'id': 'pretrained', 'label': 'RT-DETRv2-R18 COCO (PekingU, Apache-2.0)', 'hf_id': 'PekingU/rtdetr_v2_r18vd',
            'checkpoint_license': 'Apache-2.0 (model card)', 'commercial_use': True, 'commercially_deployable': True,
            'fine_tuning_allowed': True, 'redistribution': 'allowed with license notice', 'hosting_restrictions': 'none',
            'attribution': 'RT-DETRv2 authors (Apache-2.0); COCO-pretrained like the torchvision models', 'checksum': None,
            'revision': '5650961749fa93567c0d46fc7f43ea4f9e914107', 'source': 'https://huggingface.co/PekingU/rtdetr_v2_r18vd',
            'note': 'Starts from a model already trained to find objects in photos, so it learns your symbols faster.',
        }, SCRATCH],
    },
    {
        'id': 'inst-maskrcnn-mbv3', 'plain_name': 'Shape-tracing counter', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'Mask R-CNN MobileNetV3-FPN',
        'architecture': 'torchvision.models.detection.MaskRCNN + mobilenet_v3_large FPN backbone', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': "Finds and counts items and traces each one's exact shape, not just a box. Needs more labeled sheets than the others.",
        'gpu_recommended': 'T4 / A10G', 'badge': 'Traces exact shapes', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'inst-maskrcnn-r50-v2', 'plain_name': 'Large shape-tracing counter', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'Mask R-CNN ResNet-50-FPN v2',
        'architecture': 'torchvision.models.detection.maskrcnn_resnet50_fpn_v2', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': 'A bigger version of the shape tracer for large projects. Needs a powerful computer to train.', 'gpu_recommended': 'A10G / A100', 'cpu_trainable': False,
        'inits': [SCRATCH, {
            'id': 'pretrained', 'label': 'torchvision COCO checkpoint', 'weights_enum': 'MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1',
            'checkpoint_license': 'Distributed with torchvision (BSD-3-Clause); COCO-trained', 'commercial_use': 'review_required',
            'commercially_deployable': False, 'fine_tuning_allowed': True, 'redistribution': 'review_required',
            'hosting_restrictions': 'review_required', 'attribution': 'torchvision, COCO', 'checksum': None, 'revision': 'COCO_V1',
            'note': "Starts from a model trained on everyday photos. Its license is still being checked, so models trained from it can't be put to use yet.",
        }],
    },
    {
        'id': 'gnn-gps-node', 'plain_name': 'Long-run line labeler', 'task': 'node_classification', 'family': 'gnn', 'name': 'Graph transformer (GPS + GINE)',
        'architecture': 'torch_geometric GPSConv(GINEConv with edge features, multi-head global attention) x3 + MLP', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Labels every line in PDF or CAD files. Best for long runs like duct, pipe and conduit. Doesn't work on scans.",
        'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH], 'badge': 'Best for long runs', 'recommended': True,
    },
    {
        'id': 'gnn-sage-node', 'plain_name': 'Fast line labeler', 'task': 'node_classification', 'family': 'gnn', 'name': 'GraphSAGE node classifier',
        'architecture': 'torch_geometric.nn.SAGEConv x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Labels every line in PDF or CAD files. Stays fast even on very busy sheets. Doesn't work on scans.",
        'gpu_recommended': 'none (CPU ok)', 'badge': 'Fast on busy sheets', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-gat-node', 'plain_name': 'Symbol-aware line labeler', 'task': 'node_classification', 'family': 'gnn', 'name': 'GATv2 node classifier (edge-aware)',
        'architecture': 'torch_geometric.nn.GATv2Conv(edge_dim) x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Labels every line in PDF or CAD files. Good at symbols and at spots where lines meet. Doesn't work on scans.",
        'gpu_recommended': 'none (CPU ok)', 'badge': 'Good at symbols', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-gcn-node', 'plain_name': 'Basic line labeler', 'task': 'node_classification', 'family': 'gnn', 'name': 'GCN node classifier',
        'architecture': 'torch_geometric.nn.GCNConv x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': "The simplest line labeler. Use it to compare against the others. Doesn't work on scans.", 'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-sage-edge', 'plain_name': 'Line connector', 'task': 'edge_classification', 'family': 'gnn', 'name': 'GraphSAGE relation classifier',
        'architecture': 'SAGEConv encoder + MLP([h_u, h_v, |h_u-h_v|, edge_attr])', **PYG, 'version': 'torch_geometric 2.8',
        'description': "Joins separate lines into whole runs and symbols, so you can measure a pipe's total length or count a fixture once. Doesn't work on scans.",
        'gpu_recommended': 'none (CPU ok)', 'badge': 'Measures runs', 'cpu_trainable': True, 'inits': [SCRATCH],
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
        'kentucky_models_note': 'Our own starting point trained on construction drawings. Coming soon.',
        'open_models': CATALOG,
        'checkpoint_init': CHECKPOINT_INIT,
        'segmentation_assist': SEGMENTATION_ASSIST,
    }
