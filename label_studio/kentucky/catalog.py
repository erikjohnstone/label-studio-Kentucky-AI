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
        'description': 'Lightweight semantic segmentation; fast on CPU, good baseline for walls / finishes / rooms.',
        'gpu_recommended': 'none (CPU ok) / T4', 'cpu_trainable': True,
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
        'description': 'Self-supervised ViT backbone pretrained by Meta on 142M images, with a multi-scale head for thin linework. '
                       'Measured: on 10 scanned plans (7 for training) mean IoU 0.74 vs 0.63 for LR-ASPP, every item found; on a '
                       '2-sheet set it trailed (0.10 vs 0.34). Use it once you have 5+ checked sheets; about 4x the training time.',
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True, 'badge': 'Best with 5+ sheets', 'min_sheets': 5,
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
        'description': 'Transformer segmentation. Scratch init only: NVIDIA SegFormer checkpoints are released under the '
                       'NVIDIA Source Code License (non-commercial) and are EXCLUDED from the commercial catalog.',
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True,
        'inits': [SCRATCH],
        'excluded_checkpoints': [{'id': 'nvidia/mit-b0', 'reason': 'NVIDIA Source Code License - non-commercial'}],
    },
    {
        'id': 'det-dfine-s', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'D-FINE-S (pretrained)',
        'architecture': 'transformers.DFineForObjectDetection (HGNetV2-S backbone, fine-grained box refinement); outlines are boxes',
        **HF, 'version': 'transformers>=4.52',
        'description': 'DETR-family detector with fine-grained box refinement, 10M parameters. Measured on 10 scanned plans: mAP50 0.95 '
                       '(doors 12/12, windows 11/11, walls 45/47) vs 0.75 for RT-DETRv2. On 13 vector plans it scored 0.78 vs 0.89, '
                       'so it is the pick for scanned plan sets. Gives boxes.',
        'gpu_recommended': 'T4 / A10G (CPU ok for small sets)', 'cpu_trainable': True, 'badge': 'Best for scans', 'best_for': 'scan',
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
        'id': 'det-rtdetrv2-r18', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'RT-DETRv2 R18 (pretrained)',
        'architecture': 'transformers.RTDetrV2ForObjectDetection (ResNet-18-vd, 300 queries); outlines are boxes', **HF, 'version': 'transformers>=4.49',
        'description': 'Real-time detection transformer pretrained on COCO. Measured on 13 vector plans: mAP50 0.89 (doors 34/34, windows '
                       '22/22) vs 0.78 for D-FINE-S; on 10 scanned plans 0.75 vs 0.95, so it is the pick for vector PDF / DXF plan sets. '
                       'Gives boxes.',
        'gpu_recommended': 'T4 / A10G (CPU ok for small sets)', 'cpu_trainable': True, 'badge': 'Best for vector PDFs', 'best_for': 'vector',
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
        'description': 'Instance segmentation (doors, windows, fixtures, devices) with boxes + masks. CPU-trainable at small sizes.',
        'gpu_recommended': 'T4 / A10G', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'inst-maskrcnn-r50-v2', 'task': 'instance_segmentation', 'family': 'cv', 'name': 'Mask R-CNN ResNet-50-FPN v2',
        'architecture': 'torchvision.models.detection.maskrcnn_resnet50_fpn_v2', **TORCHVISION, 'version': 'torchvision 0.29',
        'description': 'Higher-capacity instance segmentation; GPU recommended.', 'gpu_recommended': 'A10G / A100', 'cpu_trainable': False,
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
        'description': 'Each line sees both its touching neighbours (with how they touch, cross or run parallel) and every other line '
                       'on the sheet through attention. Recommended by the base-model research for CAD symbol spotting. No public '
                       'pretrained checkpoint is licensed for commercial use, so it trains from zero or from your versions. '
                       'Measured on 13 vector plans: macro-F1 1.00 vs 0.99 GATv2 / GCN and 0.99 GraphSAGE, in 12 s on CPU.',
        'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH], 'badge': 'Recommended', 'recommended': True,
    },
    {
        'id': 'gnn-sage-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'GraphSAGE node classifier',
        'architecture': 'torch_geometric.nn.SAGEConv x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': 'Classifies vector primitives (wall / door / window / room tag ...) from geometry + topology.',
        'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-gat-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'GATv2 node classifier (edge-aware)',
        'architecture': 'torch_geometric.nn.GATv2Conv(edge_dim) x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': 'Attention over neighbours using candidate-edge features (touch / cross / parallel / near).',
        'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-gcn-node', 'task': 'node_classification', 'family': 'gnn', 'name': 'GCN node classifier',
        'architecture': 'torch_geometric.nn.GCNConv x3 + MLP head', **PYG, 'version': 'torch_geometric 2.8',
        'description': 'Simple spectral baseline.', 'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH],
    },
    {
        'id': 'gnn-sage-edge', 'task': 'edge_classification', 'family': 'gnn', 'name': 'GraphSAGE relation classifier',
        'architecture': 'SAGEConv encoder + MLP([h_u, h_v, |h_u-h_v|, edge_attr])', **PYG, 'version': 'torch_geometric 2.8',
        'description': 'Classifies candidate edges into relations (same_object, connects_to, hosted_by ... / none).',
        'gpu_recommended': 'none (CPU ok)', 'cpu_trainable': True, 'inits': [SCRATCH],
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
