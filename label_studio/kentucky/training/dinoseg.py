"""DINOv2 (with registers) segmentation for drawings. Django-free.

Backbone: ``facebook/dinov2-with-registers-small`` (Apache-2.0 code and weights, pinned revision) — self-supervised
ViT features that transfer well to line drawings. Head: multi-layer patch features fused with a shallow
full-resolution convolution branch, because plan linework (walls, door swings) is thinner than one 14 px patch.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

HF_ID = 'facebook/dinov2-with-registers-small'
HF_REVISION = '0d9846e56b43a21fa46d7f3f5070f0506a5795a9'
LAYERS = (3, 6, 9, 12)  # hidden states fused by the head
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def _config():
    from transformers import Dinov2WithRegistersConfig

    return Dinov2WithRegistersConfig(hidden_size=384, num_hidden_layers=12, num_attention_heads=6, num_register_tokens=4,
                                     patch_size=14, image_size=518, mlp_ratio=4, layerscale_value=1.0)


def _gn(c):
    return nn.GroupNorm(8, c)


def _block(cin, cout, stride=1):
    return nn.Sequential(nn.Conv2d(cin, cout, 3, stride=stride, padding=1), _gn(cout), nn.GELU(),
                         nn.Conv2d(cout, cout, 3, padding=1), _gn(cout), nn.GELU())


class DinoSeg(nn.Module):
    """DINOv2 context (what a line *is*) + a small convolutional encoder at 1/1, 1/2, 1/4 resolution (where exactly
    the line is), fused U-Net style. Plan walls are a few pixels thick: thinner than one 14 px ViT patch."""

    def __init__(self, num_classes: int, pretrained: bool):
        super().__init__()
        from transformers import Dinov2WithRegistersModel

        self.backbone = (Dinov2WithRegistersModel.from_pretrained(HF_ID, revision=HF_REVISION) if pretrained
                         else Dinov2WithRegistersModel(_config()))
        d = self.backbone.config.hidden_size
        self.fuse = nn.Sequential(nn.Conv2d(d * len(LAYERS), 256, 1), _gn(256), nn.GELU(), nn.Conv2d(256, 128, 3, padding=1), _gn(128), nn.GELU())
        self.e1, self.e2, self.e4 = _block(3, 32), _block(32, 64, 2), _block(64, 96, 2)
        self.d4, self.d2, self.d1 = _block(128 + 96, 128), _block(128 + 64, 96), _block(96 + 32, 64)
        self.out = nn.Conv2d(64, num_classes, 1)

    def param_groups(self, lr: float, backbone_mult: float = 0.1):
        head = [p for n, p in self.named_parameters() if not n.startswith('backbone.')]
        return [{'params': self.backbone.parameters(), 'lr': lr * backbone_mult}, {'params': head, 'lr': lr}]

    def forward(self, x):
        # x: (B,3,H,W) in [-1,1] (shared transform) -> ImageNet normalisation expected by DINOv2
        H, W = x.shape[-2:]
        img = (x * 0.5 + 0.5 - MEAN.to(x)) / STD.to(x)
        ph, pw = (28 - H % 28) % 28, (28 - W % 28) % 28  # multiple of 14 (ViT) and 4 (encoder)
        xp = F.pad(img, (0, pw, 0, ph), mode='replicate')
        h, w = xp.shape[-2] // 14, xp.shape[-1] // 14
        hs = self.backbone(pixel_values=xp, output_hidden_states=True).hidden_states
        skip = 1 + self.backbone.config.num_register_tokens  # CLS + registers
        ctx = self.fuse(torch.cat([hs[i][:, skip:, :].transpose(1, 2).reshape(x.shape[0], -1, h, w) for i in LAYERS], 1))
        f1 = self.e1(xp)
        f2 = self.e2(f1)
        f4 = self.e4(f2)
        up = lambda t, ref: F.interpolate(t, size=ref.shape[-2:], mode='bilinear', align_corners=False)  # noqa: E731
        y = self.d4(torch.cat([up(ctx, f4), f4], 1))
        y = self.d2(torch.cat([up(y, f2), f2], 1))
        y = self.d1(torch.cat([up(y, f1), f1], 1))
        return self.out(y)[..., :H, :W]
