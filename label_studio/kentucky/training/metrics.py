"""Evaluation metrics (computed from real predictions; never synthesized). Django-free."""

from __future__ import annotations

import numpy as np


def confusion(y_true, y_pred, n):
    m = np.zeros((n, n), dtype=np.int64)
    for t, p in zip(np.asarray(y_true).ravel(), np.asarray(y_pred).ravel()):
        if 0 <= t < n and 0 <= p < n:
            m[t, p] += 1
    return m


def classification_report(y_true, y_pred, classes):
    n = len(classes)
    cm = confusion(y_true, y_pred, n)
    tp = np.diag(cm).astype(float)
    fp = cm.sum(0) - tp
    fn = cm.sum(1) - tp
    support = cm.sum(1)
    prec = np.divide(tp, tp + fp, out=np.zeros(n), where=(tp + fp) > 0)
    rec = np.divide(tp, tp + fn, out=np.zeros(n), where=(tp + fn) > 0)
    f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros(n), where=(prec + rec) > 0)
    present = support > 0
    total = cm.sum()
    return {
        'accuracy': float(tp.sum() / total) if total else 0.0,
        'macro_f1': float(f1[present].mean()) if present.any() else 0.0,
        'micro_f1': float(tp.sum() / total) if total else 0.0,  # single-label multiclass: micro-F1 == accuracy
        'per_class': {c: {'precision': float(prec[i]), 'recall': float(rec[i]), 'f1': float(f1[i]), 'support': int(support[i])}
                      for i, c in enumerate(classes)},
        'confusion_matrix': cm.tolist(),
        'classes': list(classes),
        'n': int(total),
    }


def segmentation_report(pred: np.ndarray, gt: np.ndarray, classes: list[str], ignore_background_in_mean=True):
    """pred/gt: int arrays of class indices (0 = background, i = classes[i-1])."""
    n = len(classes) + 1
    cm = confusion(gt.ravel(), pred.ravel(), n)
    tp = np.diag(cm).astype(float)
    fp = cm.sum(0) - tp
    fn = cm.sum(1) - tp
    iou = np.divide(tp, tp + fp + fn, out=np.full(n, np.nan), where=(tp + fp + fn) > 0)
    dice = np.divide(2 * tp, 2 * tp + fp + fn, out=np.full(n, np.nan), where=(2 * tp + fp + fn) > 0)
    prec = np.divide(tp, tp + fp, out=np.full(n, np.nan), where=(tp + fp) > 0)
    rec = np.divide(tp, tp + fn, out=np.full(n, np.nan), where=(tp + fn) > 0)
    sel = slice(1, None) if ignore_background_in_mean else slice(None)
    gt_present = cm.sum(1) > 0
    mask = gt_present.copy()
    if ignore_background_in_mean:
        mask[0] = False
    per = {}
    for i, name in enumerate(['__background__'] + list(classes)):
        per[name] = {'iou': _f(iou[i]), 'dice': _f(dice[i]), 'precision': _f(prec[i]), 'recall': _f(rec[i]),
                     'gt_pixels': int(cm[i].sum()), 'pred_pixels': int(cm[:, i].sum())}
    return {
        'mean_iou': _f(np.nanmean(iou[mask])) if mask.any() else None,
        'mean_dice': _f(np.nanmean(dice[mask])) if mask.any() else None,
        'pixel_accuracy': float(tp.sum() / cm.sum()) if cm.sum() else 0.0,
        'per_class': per,
        'confusion_matrix': cm.tolist(),
        'classes': ['__background__'] + list(classes),
        '_mean_over': [c for c, m in zip(['__background__'] + list(classes), mask) if m] if sel else None,
    }


def _f(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, np.floating) and np.isnan(v)) else float(v)


def component_counts(mask_cls: np.ndarray, classes, min_area=6):
    """Connected-component counts per class (object count proxy for semantic masks)."""
    import cv2

    out = {}
    for i, c in enumerate(classes, start=1):
        m = (mask_cls == i).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        out[c] = int(sum(1 for k in range(1, n) if stats[k, cv2.CC_STAT_AREA] >= min_area))
    return out


def object_metrics(pred: np.ndarray, gt_instances: list[dict], classes, iou_thr=0.5):
    """Construction metrics: per-class count error + missing-object rate (GT objects w/o a matching prediction)."""
    pc = component_counts(pred, classes)
    out = {}
    for i, c in enumerate(classes, start=1):
        gts = [g for g in gt_instances if g['label'] == c]
        if not gts:
            continue
        missed = 0
        for g in gts:
            m = g['mask']
            inter = np.logical_and(m, pred == i).sum()
            cover = inter / max(m.sum(), 1)
            if cover < iou_thr:
                missed += 1
        out[c] = {'gt_count': len(gts), 'pred_components': pc.get(c, 0), 'count_error': pc.get(c, 0) - len(gts),
                  'missing_rate': missed / len(gts)}
    return out


def boundary_f1(pred: np.ndarray, gt: np.ndarray, tol=2):
    import cv2

    k = np.ones((3, 3), np.uint8)

    def edges(a):
        a = a.astype(np.uint8)
        return (cv2.morphologyEx(a, cv2.MORPH_GRADIENT, k) > 0)

    pe, ge = edges(pred > 0), edges(gt > 0)
    if pe.sum() == 0 and ge.sum() == 0:
        return 1.0
    kd = np.ones((2 * tol + 1, 2 * tol + 1), np.uint8)
    gd = cv2.dilate(ge.astype(np.uint8), kd) > 0
    pd = cv2.dilate(pe.astype(np.uint8), kd) > 0
    p = (pe & gd).sum() / max(pe.sum(), 1)
    r = (ge & pd).sum() / max(ge.sum(), 1)
    return float(2 * p * r / (p + r)) if p + r > 0 else 0.0


def mask_iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return inter / union if union else 0.0


def average_precision(preds, gts, classes, iou_thr=0.5):
    """Mask AP per class at an IoU threshold (VOC-style all-point interpolation).

    preds: list per image of [{'label', 'score', 'mask'}]; gts: list per image of [{'label', 'mask'}].
    """
    aps = {}
    pr = {}
    for c in classes:
        scored = []
        npos = 0
        for img_preds, img_gts in zip(preds, gts):
            g = [x for x in img_gts if x['label'] == c]
            npos += len(g)
            used = [False] * len(g)
            for p in sorted([x for x in img_preds if x['label'] == c], key=lambda x: -x['score']):
                best, bj = 0.0, -1
                for j, gg in enumerate(g):
                    if used[j]:
                        continue
                    iou = mask_iou(p['mask'], gg['mask'])
                    if iou > best:
                        best, bj = iou, j
                if best >= iou_thr:
                    used[bj] = True
                    scored.append((p['score'], 1))
                else:
                    scored.append((p['score'], 0))
        if npos == 0:
            continue
        scored.sort(key=lambda x: -x[0])
        tps = np.cumsum([s[1] for s in scored]) if scored else np.array([0])
        fps = np.cumsum([1 - s[1] for s in scored]) if scored else np.array([0])
        rec = tps / npos
        prec = tps / np.maximum(tps + fps, 1)
        mrec = np.concatenate([[0], rec, [1]])
        mpre = np.concatenate([[0], prec, [0]])
        for i in range(len(mpre) - 2, -1, -1):
            mpre[i] = max(mpre[i], mpre[i + 1])
        idx = np.where(mrec[1:] != mrec[:-1])[0]
        aps[c] = float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))
        tp_total = int(tps[-1]) if len(scored) else 0
        pr[c] = {'precision': tp_total / max(len(scored), 1), 'recall': tp_total / npos, 'tp': tp_total,
                 'fp': len(scored) - tp_total, 'fn': npos - tp_total}
    return {'mAP@50' if iou_thr == 0.5 else f'mAP@{int(iou_thr * 100)}': float(np.mean(list(aps.values()))) if aps else None,
            'per_class_ap': aps, 'per_class_pr': pr}
