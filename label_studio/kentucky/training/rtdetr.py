"""RT-DETRv2 (ResNet-18-vd) for finding items one by one on drawings. Django-free.

Weights: ``PekingU/rtdetr_v2_r18vd`` (Apache-2.0, COCO-pretrained, pinned revision). The adapter makes the
Hugging Face model behave like a torchvision detection model (``model(images, targets) -> losses`` in training,
``model(images) -> [{boxes, labels, scores}]`` in eval), so the shared item-by-item training loop, evaluation,
inference and API work unchanged. RT-DETR predicts boxes; an item's outline is its box.
"""

from __future__ import annotations

import json
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

HF_ID = 'PekingU/rtdetr_v2_r18vd'
HF_REVISION = '5650961749fa93567c0d46fc7f43ea4f9e914107'
CONFIG = Path(__file__).with_name('configs') / 'rtdetr_v2_r18vd.json'  # vendored from the pinned revision (Apache-2.0)
MAX_DETECTIONS = 200


def _config(num_labels: int):
    from transformers import RTDetrV2Config

    cfg = RTDetrV2Config.from_dict(json.loads(CONFIG.read_text()))
    cfg.num_labels = num_labels
    cfg.id2label = {i: f'class_{i}' for i in range(num_labels)}
    cfg.label2id = {v: k for k, v in cfg.id2label.items()}
    return cfg


def _box_cxcywh_to_xyxy(b):
    cx, cy, w, h = b.unbind(-1)
    return torch.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], -1)


class RTDetrAdapter(nn.Module):
    def __init__(self, num_classes: int, pretrained: bool):
        """num_classes includes background (torchvision convention); RT-DETR itself has no background class."""
        super().__init__()
        from transformers import RTDetrV2ForObjectDetection

        k = num_classes - 1
        if pretrained:
            self.net = RTDetrV2ForObjectDetection.from_pretrained(HF_ID, revision=HF_REVISION, config=_config(k), ignore_mismatched_sizes=True)
        else:
            self.net = RTDetrV2ForObjectDetection(_config(k))

    @staticmethod
    def _batch(images):
        # shared transform gives [-1, 1]; RT-DETR expects [0, 1] (rescale only, no normalisation); pad to /32 with white
        H = max(i.shape[-2] for i in images)
        W = max(i.shape[-1] for i in images)
        H, W = H + (32 - H % 32) % 32, W + (32 - W % 32) % 32
        x = torch.ones(len(images), 3, H, W)
        for n, im in enumerate(images):
            x[n, :, :im.shape[-2], :im.shape[-1]] = im * 0.5 + 0.5
        return x, H, W

    def forward(self, images, targets=None):
        x, H, W = self._batch(images)
        scale = torch.tensor([W, H, W, H], dtype=torch.float32)
        if self.training:
            labels = []
            for t in targets:
                b = t['boxes'].float()
                if len(b):
                    cxcywh = torch.stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2, b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], -1) / scale
                else:
                    cxcywh = torch.zeros((0, 4))
                labels.append({'class_labels': t['labels'] - 1, 'boxes': cxcywh.clamp(0, 1)})
            out = self.net(pixel_values=x, labels=labels)
            return {'loss': out.loss}
        out = self.net(pixel_values=x)
        prob = out.logits.sigmoid()  # (B, Q, K) focal-style scores
        res = []
        for n, im in enumerate(images):
            h, w = im.shape[-2:]
            p = prob[n]
            k = min(MAX_DETECTIONS, p.numel())
            scores, idx = p.flatten().topk(k)
            q, cls = idx // p.shape[1], idx % p.shape[1]
            boxes = _box_cxcywh_to_xyxy(out.pred_boxes[n][q]) * scale
            boxes[:, 0::2] = boxes[:, 0::2].clamp(0, w)
            boxes[:, 1::2] = boxes[:, 1::2].clamp(0, h)
            keep = (boxes[:, 2] - boxes[:, 0] > 1) & (boxes[:, 3] - boxes[:, 1] > 1)
            res.append({'boxes': boxes[keep], 'labels': cls[keep] + 1, 'scores': scores[keep]})
        return res
