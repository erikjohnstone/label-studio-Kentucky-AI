"""CV training tracks: semantic segmentation (LR-ASPP, SegFormer) and instance segmentation (Mask R-CNN).

Reads a dataset export bundle (kentucky.datasets.export). Django-free so it runs unchanged in a
local subprocess or inside a cloud GPU container.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from . import metrics as M
from .events import check_cancel

# ----------------------------------------------------------------------------- data


def load_bundle(bundle: Path):
    meta = json.loads((bundle / 'manifest.json').read_text())
    classes = meta.get('cv_classes') or [c['name'] for c in meta['taxonomy']['classes'] if c['kind'] == 'cv' and c['name'] != 'unknown']
    return meta, classes


def _load_gray(p: Path, scale: float) -> np.ndarray:
    im = Image.open(p).convert('L')
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def _load_mask(p: Path, scale: float, size) -> np.ndarray:
    im = Image.open(p)
    if scale != 1.0:
        im = im.resize(size, Image.NEAREST)
    return np.asarray(im, dtype=np.int64)


def to_input(gray: np.ndarray) -> torch.Tensor:
    """(H,W) in [0,1] -> (3,H,W) normalized. Same transform at train and inference time."""
    x = torch.from_numpy((gray - 0.5) / 0.5).float()
    return x.unsqueeze(0).repeat(3, 1, 1)


def augment(img, mask, aug, rng):
    if 'flip' in aug and rng.random() < 0.5:
        img, mask = img[:, ::-1], mask[:, ::-1]
    if 'flip' in aug and rng.random() < 0.5:
        img, mask = img[::-1], mask[::-1]
    if 'rot90' in aug:
        k = rng.randint(0, 3)
        img, mask = np.rot90(img, k), np.rot90(mask, k)
    if 'brightness' in aug:
        img = np.clip(img * rng.uniform(0.85, 1.1) + rng.uniform(-0.08, 0.08), 0, 1)
    if 'noise' in aug and rng.random() < 0.5:
        img = np.clip(img + np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 0.04, img.shape), 0, 1)
    return np.ascontiguousarray(img), np.ascontiguousarray(mask)


def random_crops(img, mask, size, n, rng, fg_bias=0.7):
    H, W = img.shape
    out = []
    if H < size or W < size:
        ph, pw = max(0, size - H), max(0, size - W)
        img = np.pad(img, ((0, ph), (0, pw)), constant_values=1.0)
        mask = np.pad(mask, ((0, ph), (0, pw)), constant_values=0)
        H, W = img.shape
    fg = np.argwhere(mask > 0)
    for _ in range(n):
        if len(fg) and rng.random() < fg_bias:
            cy, cx = fg[rng.randrange(len(fg))]
            y = int(np.clip(cy - size // 2 + rng.randint(-size // 4, size // 4), 0, H - size))
            x = int(np.clip(cx - size // 2 + rng.randint(-size // 4, size // 4), 0, W - size))
        else:
            y, x = rng.randint(0, H - size), rng.randint(0, W - size)
        out.append((img[y:y + size, x:x + size], mask[y:y + size, x:x + size]))
    return out


# ----------------------------------------------------------------------------- models


def build_semantic(catalog_id: str, num_classes: int, init: str, reporter=None):
    """num_classes includes background."""
    if catalog_id == 'seg-lraspp-mbv3':
        from torchvision.models.segmentation import LRASPP_MobileNet_V3_Large_Weights, lraspp_mobilenet_v3_large

        if init == 'pretrained':
            m = lraspp_mobilenet_v3_large(weights=LRASPP_MobileNet_V3_Large_Weights.COCO_WITH_VOC_LABELS_V1)
            # replace the classifier heads for our classes
            m.classifier.low_classifier = torch.nn.Conv2d(m.classifier.low_classifier.in_channels, num_classes, 1)
            m.classifier.high_classifier = torch.nn.Conv2d(m.classifier.high_classifier.in_channels, num_classes, 1)
        else:
            m = lraspp_mobilenet_v3_large(weights=None, weights_backbone=None, num_classes=num_classes)
        return m
    if catalog_id == 'seg-dinov2-s':
        from .dinoseg import DinoSeg

        if reporter is not None and init == 'pretrained':
            reporter.log('Loading DINOv2-with-registers-small (Apache-2.0) pretrained backbone')
        return DinoSeg(num_classes, pretrained=(init == 'pretrained'))
    if catalog_id == 'seg-segformer-b0':
        from transformers import SegformerConfig, SegformerForSemanticSegmentation

        cfg = SegformerConfig(num_labels=num_classes, depths=[2, 2, 2, 2], hidden_sizes=[32, 64, 160, 256],
                              decoder_hidden_size=256, num_channels=3)
        return SegformerForSemanticSegmentation(cfg)
    raise ValueError(catalog_id)


def semantic_forward(model, catalog_id, x):
    if catalog_id == 'seg-dinov2-s':
        return model(x)
    if catalog_id == 'seg-segformer-b0':
        logits = model(pixel_values=x).logits
        return F.interpolate(logits, size=x.shape[-2:], mode='bilinear', align_corners=False)
    return model(x)['out']


def _pad32(x):
    H, W = x.shape[-2:]
    ph, pw = (32 - H % 32) % 32, (32 - W % 32) % 32
    return F.pad(x, (0, pw, 0, ph), value=1.0), (H, W)


@torch.no_grad()
def predict_semantic(model, catalog_id, gray: np.ndarray, tile: int = 768, return_prob: bool = False):
    """Full-sheet inference with overlapping tiles. Returns (class map, max-prob map) at input res."""
    model.eval()
    H, W = gray.shape
    if max(H, W) <= tile:
        x, (h, w) = _pad32(to_input(gray).unsqueeze(0))
        prob = torch.softmax(semantic_forward(model, catalog_id, x), 1)[0, :, :h, :w]
    else:
        n_cls = None
        acc = None
        cnt = torch.zeros((H, W))
        step = tile - tile // 4
        for y in list(range(0, max(H - tile, 0) + 1, step)) + ([H - tile] if H > tile else []):
            for x0 in list(range(0, max(W - tile, 0) + 1, step)) + ([W - tile] if W > tile else []):
                y, x0 = max(0, y), max(0, x0)
                crop = gray[y:y + tile, x0:x0 + tile]
                xt, (h, w) = _pad32(to_input(crop).unsqueeze(0))
                p = torch.softmax(semantic_forward(model, catalog_id, xt), 1)[0, :, :h, :w]
                if acc is None:
                    n_cls = p.shape[0]
                    acc = torch.zeros((n_cls, H, W))
                acc[:, y:y + h, x0:x0 + w] += p
                cnt[y:y + h, x0:x0 + w] += 1
        prob = acc / cnt.clamp(min=1)
    conf, cls = prob.max(0)
    if return_prob:
        return cls.numpy().astype(np.int64), conf.numpy(), prob
    return cls.numpy().astype(np.int64), conf.numpy()


def recalibrate_bn(model, forward, batches):
    """Precise-BN: recompute BatchNorm running statistics with the final weights on training crops.

    Models trained from scratch with small batches have unreliable running stats, which makes eval-mode
    output collapse. Recomputing them (cumulative average, no gradient) before every evaluation and before a
    checkpoint is saved makes eval/inference consistent with what the network learned."""
    bns = [m for m in model.modules() if isinstance(m, torch.nn.modules.batchnorm._BatchNorm)]
    if not bns:
        return
    saved = [b.momentum for b in bns]
    for b in bns:
        b.reset_running_stats()
        b.momentum = None
    model.train()
    with torch.no_grad():
        for x in batches:
            forward(x)
    for b, mom in zip(bns, saved):
        b.momentum = mom
    model.eval()


def make_optimizer(params, cfg):
    if cfg['optimizer'] == 'sgd':
        return torch.optim.SGD(params, lr=cfg['lr'], momentum=0.9, weight_decay=cfg['weight_decay'])
    if cfg['optimizer'] == 'adam':
        return torch.optim.Adam(params, lr=cfg['lr'], weight_decay=cfg['weight_decay'])
    return torch.optim.AdamW(params, lr=cfg['lr'], weight_decay=cfg['weight_decay'])


def make_scheduler(opt, cfg):
    if cfg['scheduler'] == 'cosine':
        return torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(cfg['epochs'], 1))
    if cfg['scheduler'] == 'step':
        return torch.optim.lr_scheduler.StepLR(opt, step_size=max(cfg['epochs'] // 3, 1), gamma=0.1)
    if cfg['scheduler'] == 'plateau':
        return torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.5, patience=5)
    return None


def class_weights(counts: np.ndarray, mode: str):
    """Inverse-frequency weights over PRESENT classes; absent classes get weight 0 (cannot be learned)."""
    counts = np.asarray(counts, dtype=float)
    if mode == 'none':
        return None
    present = counts > 0
    w = np.zeros_like(counts)
    w[present] = (counts[present].sum() / counts[present]) ** (0.5 if mode == 'sqrt_inverse' else 1.0)
    w[present] = w[present] / w[present].mean()
    return torch.tensor(w, dtype=torch.float32)


# ----------------------------------------------------------------------------- semantic track


def train_semantic(spec, reporter, deadline):
    bundle, out = Path(spec['bundle_dir']), Path(spec['out_dir'])
    cfg, cid = spec['config'], spec['catalog_id']
    meta, classes = load_bundle(bundle)
    rng = random.Random(cfg['seed'])
    torch.manual_seed(cfg['seed'])
    np.random.seed(cfg['seed'])
    s = cfg['training_scale']
    splits = meta['splits']

    def load(ids):
        items = []
        for sid in ids:
            img = _load_gray(bundle / 'images' / f'{sid}.png', s)
            m = _load_mask(bundle / 'semantic' / f'{sid}.png', s, (img.shape[1], img.shape[0]))
            items.append((sid, img, m))
        return items

    train, val, test = load(splits['train']), load(splits['val']), load(splits['test'])
    if not train:
        raise ValueError('Training split is empty')
    if not val:
        reporter.log('Validation split empty: using training sheets for validation (metrics will be optimistic)')
        val = train
    nC = len(classes) + 1
    counts = np.bincount(np.concatenate([m.ravel() for _, _, m in train]), minlength=nC)[:nC]
    weights = class_weights(counts, cfg.get('class_weighting', 'sqrt_inverse'))
    model = build_semantic(cid, nC, spec['init'], reporter)
    start_epoch = 0
    if spec.get('base_checkpoint'):
        ck = torch.load(spec['base_checkpoint'], map_location='cpu', weights_only=False)
        _load_compatible(model, ck['state_dict'], reporter)
        if spec.get('resume') and ck.get('optimizer_state'):
            start_epoch = ck.get('epoch', 0)
    opt = make_optimizer(model.param_groups(cfg['lr']) if hasattr(model, 'param_groups') else model.parameters(), cfg)
    sched = make_scheduler(opt, cfg)
    best, best_epoch, bad = -1.0, -1, 0
    reporter.status('TRAINING', classes=classes, train_sheets=len(train), val_sheets=len(val), class_pixel_counts=counts.tolist())
    for epoch in range(start_epoch, cfg['epochs']):
        check_cancel(spec['job_dir'])
        if time.time() > deadline:
            raise TimeoutError('max runtime exceeded')
        model.train()
        batch = []
        for _, img, m in train:
            for ci, cm_ in random_crops(img, m, cfg['crop_size'], cfg['crops_per_sheet'], rng):
                batch.append(augment(ci, cm_, cfg.get('augment', []), rng))
        rng.shuffle(batch)
        losses = []
        t0 = time.time()
        for i in range(0, len(batch), cfg['batch_size']):
            chunk = batch[i:i + cfg['batch_size']]
            x = torch.stack([to_input(a) for a, _ in chunk])
            y = torch.stack([torch.from_numpy(b) for _, b in chunk])
            logits = semantic_forward(model, cid, x)
            loss = F.cross_entropy(logits, y, weight=weights)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss))
            reporter.heartbeat()
        train_loss = float(np.mean(losses))
        rec = {'epoch': epoch + 1, 'train_loss': train_loss, 'lr': opt.param_groups[0]['lr'], 'epoch_s': round(time.time() - t0, 2)}
        if (epoch + 1) % cfg['val_every'] == 0 or epoch + 1 == cfg['epochs']:
            recalibrate_bn(model, lambda x: semantic_forward(model, cid, x), _bn_batches(train, cfg, cal_rng := random.Random(cfg['seed'] + 7)))
            vloss, rep = evaluate_semantic(model, cid, val, classes, weights)
            rec.update({'val_loss': vloss, 'val_mean_iou': rep['mean_iou'], 'val_mean_dice': rep['mean_dice']})
            score = rep['mean_iou'] or 0.0
            if score > best:
                best, best_epoch, bad = score, epoch + 1, 0
                save_checkpoint(out / 'best.pt', model, spec, classes, epoch + 1, rep)
            else:
                bad += 1
            if sched is not None and cfg['scheduler'] == 'plateau':
                sched.step(vloss)
        if sched is not None and cfg['scheduler'] != 'plateau':
            sched.step()
        reporter.metric(**rec)
        if (epoch + 1) % cfg['checkpoint_every'] == 0:
            save_checkpoint(out / f'epoch_{epoch + 1}.pt', model, spec, classes, epoch + 1, None, opt)
            reporter.emit('checkpoint', path=f'epoch_{epoch + 1}.pt', epoch=epoch + 1)
        _maybe_fault(spec, epoch)
        if bad >= cfg['early_stopping_patience']:
            reporter.log(f'Early stopping at epoch {epoch + 1} (best epoch {best_epoch})')
            break
    reporter.status('EVALUATING')
    ck = torch.load(out / 'best.pt', map_location='cpu', weights_only=False)
    model.load_state_dict(ck['state_dict'])
    final = {'best_epoch': best_epoch, 'task': 'semantic_segmentation', 'classes': classes}
    for name, items in (('val', val), ('test', test)):
        if not items:
            continue
        vloss, rep = evaluate_semantic(model, cid, items, classes, weights, with_objects=True, bundle=bundle, scale=s, meta=meta)
        final[name] = {**rep, 'loss': vloss}
    final['headline'] = {'mean_iou': (final.get('test') or final.get('val', {})).get('mean_iou'),
                         'split': 'test' if final.get('test') else 'val'}
    return final, out / 'best.pt'


def _bn_batches(train, cfg, rng, n_batches=24):
    crops = []
    for _, img, m in train:
        crops += random_crops(img, m, cfg['crop_size'], max(2, n_batches * cfg['batch_size'] // max(len(train), 1)), rng)
    rng.shuffle(crops)
    crops = crops[: n_batches * cfg['batch_size']]
    for i in range(0, len(crops), cfg['batch_size']):
        yield torch.stack([to_input(a) for a, _ in crops[i:i + cfg['batch_size']]])


def _maybe_fault(spec, epoch):
    import os

    f = spec['config'].get('_fault')
    if not f or os.environ.get('KA_ALLOW_FAULT_INJECTION') != '1':
        return
    if f == 'crash' and epoch >= 0:
        raise RuntimeError('injected worker crash')
    if f == 'hang':
        time.sleep(3600)


def _load_compatible(model, state, reporter):
    own = model.state_dict()
    ok = {k: v for k, v in state.items() if k in own and own[k].shape == v.shape}
    skipped = [k for k in state if k not in ok]
    own.update(ok)
    model.load_state_dict(own)
    if reporter:
        reporter.log(f'Loaded {len(ok)} tensors from base checkpoint; re-initialized {len(skipped)} (head / class-count changes)')


def evaluate_semantic(model, cid, items, classes, weights, with_objects=False, bundle=None, scale=1.0, meta=None):
    preds, gts, losses = [], [], []
    per_sheet = {}
    for sid, img, m in items:
        cls, _, prob = predict_semantic(model, cid, img, return_prob=True)
        with torch.no_grad():
            # weighted NLL of the (tiled) full-sheet probabilities == CE on the whole sheet
            logp = torch.log(prob.clamp(min=1e-8)).unsqueeze(0)
            losses.append(float(F.nll_loss(logp, torch.from_numpy(m).unsqueeze(0), weight=weights)))
        preds.append(cls)
        gts.append(m)
        per_sheet[sid] = {'boundary_f1': M.boundary_f1(cls, m)}
    pred = np.concatenate([p.ravel() for p in preds])
    gt = np.concatenate([g.ravel() for g in gts])
    rep = M.segmentation_report(pred, gt, classes)
    rep['boundary_f1'] = float(np.mean([v['boundary_f1'] for v in per_sheet.values()]))
    if with_objects and bundle is not None:
        objs = []
        coco = {}
        for split in ('train', 'val', 'test'):
            p = bundle / 'coco' / f'{split}.json'
            if p.exists():
                c = json.loads(p.read_text())
                for a in c['annotations']:
                    coco.setdefault(a['image_id'], []).append(a)
        names = {i + 1: c for i, c in enumerate(classes)}
        kinds = {s['id']: ('vector' if s['has_vector'] else 'raster') for s in meta['sheets']}
        by_kind = {}
        for (sid, img, _), pr in zip(items, preds):
            inst = []
            for a in coco.get(sid, []):
                mk = _ann_mask(a, img.shape, scale)
                if mk is not None:
                    inst.append({'label': names[a['category_id']], 'mask': mk})
            om = M.object_metrics(pr, inst, classes)
            objs.append(om)
            by_kind.setdefault(kinds.get(sid, 'unknown'), []).append((pr, gts[[s for s, _, _ in items].index(sid)]))
        agg = {}
        for om in objs:
            for c, v in om.items():
                a = agg.setdefault(c, {'gt_count': 0, 'pred_components': 0, 'missed': 0.0})
                a['gt_count'] += v['gt_count']
                a['pred_components'] += v['pred_components']
                a['missed'] += v['missing_rate'] * v['gt_count']
        rep['objects'] = {c: {'gt_count': a['gt_count'], 'pred_components': a['pred_components'],
                              'count_error': a['pred_components'] - a['gt_count'],
                              'missing_rate': a['missed'] / max(a['gt_count'], 1)} for c, a in agg.items()}
        rep['by_drawing_type'] = {k: M.segmentation_report(np.concatenate([p.ravel() for p, _ in v]),
                                                          np.concatenate([g.ravel() for _, g in v]), classes)['mean_iou']
                                  for k, v in by_kind.items()}
    return (float(np.mean(losses)) if losses else None), rep


def _ann_mask(a, shape, scale):
    from PIL import ImageDraw

    H, W = shape
    seg = a.get('segmentation')
    if isinstance(seg, list) and seg:
        im = Image.new('L', (W, H), 0)
        pts = [(seg[0][i] * scale, seg[0][i + 1] * scale) for i in range(0, len(seg[0]), 2)]
        ImageDraw.Draw(im).polygon(pts, fill=1)
        return np.asarray(im) > 0
    if isinstance(seg, dict):
        from .rle import rle_decode

        m = rle_decode(seg)
        return np.asarray(Image.fromarray(m * 255).resize((W, H), Image.NEAREST)) > 0
    return None


def save_checkpoint(path: Path, model, spec, classes, epoch, report, opt=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        'format': 'ka-checkpoint-1', 'catalog_id': spec['catalog_id'], 'task': spec['task'], 'init': spec['init'],
        'config': spec['config'], 'classes': classes, 'epoch': epoch, 'state_dict': model.state_dict(),
        'optimizer_state': opt.state_dict() if opt is not None else None,
        'preprocess': {'training_scale': spec['config'].get('training_scale', 1.0), 'input': 'gray->3ch, (x-0.5)/0.5',
                       'coordinate_space': 'sheet image px * training_scale'},
        'report': report,
    }, path)


# ----------------------------------------------------------------------------- instance track


def _no_resize(model):
    """Drawings are trained/served at an explicit ``training_scale``; disable torchvision's internal min/max-size
    rescale so train crops and full-sheet inference see identical pixel scales."""
    model.transform.resize = lambda image, target=None: (image, target)
    return model


def build_maskrcnn(catalog_id, num_classes, init):
    from torchvision.models.detection import MaskRCNN, maskrcnn_resnet50_fpn_v2
    from torchvision.models.detection.backbone_utils import mobilenet_backbone
    from torchvision.models.detection.rpn import AnchorGenerator

    if catalog_id == 'det-rtdetrv2-r18':
        from .rtdetr import RTDetrAdapter

        return RTDetrAdapter(num_classes, pretrained=(init == 'pretrained'))
    if catalog_id == 'inst-maskrcnn-mbv3':
        from functools import partial

        # GroupNorm: batch-size independent (FrozenBatchNorm with random init would mean no normalization at all)
        backbone = mobilenet_backbone(backbone_name='mobilenet_v3_large', weights=None, fpn=True, trainable_layers=6,
                                      norm_layer=partial(torch.nn.GroupNorm, 8))
        anchors = AnchorGenerator(sizes=((16, 32, 64, 128, 256),) * 3, aspect_ratios=((0.25, 0.5, 1.0, 2.0, 4.0),) * 3)
        m = MaskRCNN(backbone, num_classes=num_classes, rpn_anchor_generator=anchors, box_detections_per_img=200)
        return _no_resize(m)
    if catalog_id == 'inst-maskrcnn-r50-v2':
        if init == 'pretrained':
            from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights
            from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
            from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

            m = maskrcnn_resnet50_fpn_v2(weights=MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1)
            m.roi_heads.box_predictor = FastRCNNPredictor(m.roi_heads.box_predictor.cls_score.in_features, num_classes)
            m.roi_heads.mask_predictor = MaskRCNNPredictor(256, 256, num_classes)
            return _no_resize(m)
        return _no_resize(maskrcnn_resnet50_fpn_v2(weights=None, weights_backbone=None, num_classes=num_classes))
    raise ValueError(catalog_id)


def _instances_for(bundle, split, classes, scale):
    from .rle import rle_decode

    p = bundle / 'coco' / f'{split}.json'
    if not p.exists():
        return []
    c = json.loads(p.read_text())
    by_img = {im['id']: [] for im in c['images']}
    for a in c['annotations']:
        by_img.setdefault(a['image_id'], []).append(a)
    out = []
    for im in c['images']:
        gray = _load_gray(bundle / im['file_name'], scale)
        H, W = gray.shape
        inst = []
        for a in by_img[im['id']]:
            seg = a['segmentation']
            if isinstance(seg, dict):
                m = rle_decode(seg)
                m = np.asarray(Image.fromarray(m * 255).resize((W, H), Image.NEAREST)) > 0
            else:
                m = _ann_mask(a, (H, W), scale)
            if m is None or m.sum() < 4:
                continue
            ys, xs = np.nonzero(m)
            inst.append({'label': c['categories'][a['category_id'] - 1]['name'], 'cat': a['category_id'], 'mask': m,
                         'box': [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]})
        out.append((im['id'], gray, inst))
    return out


def _crop_instances(gray, inst, size, rng):
    H, W = gray.shape
    if H <= size and W <= size:
        return gray, inst
    if inst and rng.random() < 0.8:
        b = inst[rng.randrange(len(inst))]['box']
        cy, cx = (b[1] + b[3]) // 2, (b[0] + b[2]) // 2
        y = int(np.clip(cy - size // 2 + rng.randint(-size // 4, size // 4), 0, max(H - size, 0)))
        x = int(np.clip(cx - size // 2 + rng.randint(-size // 4, size // 4), 0, max(W - size, 0)))
    else:
        y, x = rng.randint(0, max(H - size, 0)), rng.randint(0, max(W - size, 0))
    g = gray[y:y + size, x:x + size]
    out = []
    for it in inst:
        m = it['mask'][y:y + size, x:x + size]
        if m.sum() < 8 or m.sum() < 0.3 * it['mask'].sum():
            continue  # drop instances mostly outside the crop
        ys, xs = np.nonzero(m)
        out.append({**it, 'mask': m, 'box': [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]})
    return g, out


def _target(inst):
    if not inst:
        return {'boxes': torch.zeros((0, 4)), 'labels': torch.zeros((0,), dtype=torch.int64),
                'masks': torch.zeros((0, 1, 1), dtype=torch.uint8)}
    return {
        'boxes': torch.tensor([i['box'] for i in inst], dtype=torch.float32),
        'labels': torch.tensor([i['cat'] for i in inst], dtype=torch.int64),
        'masks': torch.from_numpy(np.stack([i['mask'] for i in inst]).astype(np.uint8)),
    }


@torch.no_grad()
def predict_instances(model, gray, score_thr=0.5, classes=None):
    model.eval()
    x = to_input(gray)
    out = model([x])[0]
    res = []
    H, W = gray.shape
    for j, (b, lab, sc) in enumerate(zip(out['boxes'], out['labels'], out['scores'])):
        if float(sc) < score_thr:
            continue
        if 'masks' in out:
            mask = out['masks'][j][0].numpy() > 0.5
        else:  # box detectors (RT-DETR): the item's outline is its box
            mask = np.zeros((H, W), bool)
            x0, y0, x1, y1 = [int(round(float(v))) for v in b]
            mask[max(y0, 0):max(y1, y0 + 1), max(x0, 0):max(x1, x0 + 1)] = True
        res.append({'label': classes[int(lab) - 1] if classes else int(lab), 'score': float(sc),
                    'box': [float(v) for v in b], 'mask': mask})
    return res


def train_instance(spec, reporter, deadline):
    bundle, out = Path(spec['bundle_dir']), Path(spec['out_dir'])
    cfg, cid = spec['config'], spec['catalog_id']
    meta, classes = load_bundle(bundle)
    rng = random.Random(cfg['seed'])
    torch.manual_seed(cfg['seed'])
    s = cfg['training_scale']
    train = _instances_for(bundle, 'train', classes, s)
    val = _instances_for(bundle, 'val', classes, s) or train
    test = _instances_for(bundle, 'test', classes, s)
    if not train:
        raise ValueError('Training split is empty')
    model = build_maskrcnn(cid, len(classes) + 1, spec['init'])
    if spec.get('base_checkpoint'):
        ck = torch.load(spec['base_checkpoint'], map_location='cpu', weights_only=False)
        _load_compatible(model, ck['state_dict'], reporter)
    opt = make_optimizer([p for p in model.parameters() if p.requires_grad], cfg)
    sched = make_scheduler(opt, cfg)
    warmup = 50
    step = 0
    best, best_epoch, bad = -1.0, -1, 0
    reporter.status('TRAINING', classes=classes, train_sheets=len(train), val_sheets=len(val))
    for epoch in range(cfg['epochs']):
        check_cancel(spec['job_dir'])
        if time.time() > deadline:
            raise TimeoutError('max runtime exceeded')
        model.train()
        samples = []
        for _, gray, inst in train:
            for _ in range(cfg['crops_per_sheet']):
                g, it = _crop_instances(gray, inst, cfg['crop_size'], rng)
                if 'flip' in cfg.get('augment', []) and rng.random() < 0.5:
                    g = g[:, ::-1].copy()
                    W = g.shape[1]
                    it = [{**i, 'mask': i['mask'][:, ::-1].copy(), 'box': [W - i['box'][2], i['box'][1], W - i['box'][0], i['box'][3]]} for i in it]
                samples.append((g, it))
        rng.shuffle(samples)
        losses = []
        t0 = time.time()
        for i in range(0, len(samples), cfg['batch_size']):
            chunk = samples[i:i + cfg['batch_size']]
            imgs = [to_input(g) for g, _ in chunk]
            tg = [_target(it) for _, it in chunk]
            ld = model(imgs, tg)
            loss = sum(ld.values())
            if not math.isfinite(float(loss)):
                reporter.log('non-finite loss; skipping batch')
                continue
            if step < warmup:
                for gparam in opt.param_groups:
                    gparam['lr'] = cfg['lr'] * (step + 1) / warmup
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            opt.step()
            step += 1
            losses.append(float(loss))
            reporter.heartbeat()
        rec = {'epoch': epoch + 1, 'train_loss': float(np.mean(losses)) if losses else None, 'lr': opt.param_groups[0]['lr'],
               'epoch_s': round(time.time() - t0, 2)}
        if (epoch + 1) % cfg['val_every'] == 0 or epoch + 1 == cfg['epochs']:
            rep = evaluate_instance(model, val, classes, cfg.get('score_threshold', 0.5))
            rec['val_mask_map50'] = rep['mAP@50']
            score = rep['mAP@50'] or 0.0
            if score > best:
                best, best_epoch, bad = score, epoch + 1, 0
                save_checkpoint(out / 'best.pt', model, spec, classes, epoch + 1, rep)
            else:
                bad += 1
        if sched is not None and cfg['scheduler'] != 'plateau':
            sched.step()
        reporter.metric(**rec)
        if (epoch + 1) % cfg['checkpoint_every'] == 0:
            save_checkpoint(out / f'epoch_{epoch + 1}.pt', model, spec, classes, epoch + 1, None)
            reporter.emit('checkpoint', path=f'epoch_{epoch + 1}.pt', epoch=epoch + 1)
        _maybe_fault(spec, epoch)
        if bad >= cfg['early_stopping_patience']:
            reporter.log(f'Early stopping at epoch {epoch + 1}')
            break
    if not (out / 'best.pt').exists():
        save_checkpoint(out / 'best.pt', model, spec, classes, cfg['epochs'], None)
    reporter.status('EVALUATING')
    ck = torch.load(out / 'best.pt', map_location='cpu', weights_only=False)
    model.load_state_dict(ck['state_dict'])
    final = {'best_epoch': best_epoch, 'task': 'instance_segmentation', 'classes': classes}
    final['val'] = evaluate_instance(model, val, classes, cfg.get('score_threshold', 0.5))
    if test:
        final['test'] = evaluate_instance(model, test, classes, cfg.get('score_threshold', 0.5))
    final['headline'] = {'mask_map50': (final.get('test') or final['val'])['mAP@50'], 'split': 'test' if test else 'val'}
    return final, out / 'best.pt'


def evaluate_instance(model, items, classes, thr):
    preds, gts = [], []
    count = {}
    for _, gray, inst in items:
        p = predict_instances(model, gray, score_thr=0.05, classes=classes)
        preds.append(p)
        gts.append(inst)
        for c in classes:
            k = count.setdefault(c, {'gt': 0, 'pred': 0})
            k['gt'] += sum(1 for i in inst if i['label'] == c)
            k['pred'] += sum(1 for i in p if i['label'] == c and i['score'] >= thr)
    ap50 = M.average_precision(preds, gts, classes, 0.5)
    ap75 = M.average_precision(preds, gts, classes, 0.75)
    return {**ap50, 'mAP@75': ap75.get('mAP@75'),
            'count_error': {c: v['pred'] - v['gt'] for c, v in count.items() if v['gt']},
            'counts': count, 'score_threshold': thr}
