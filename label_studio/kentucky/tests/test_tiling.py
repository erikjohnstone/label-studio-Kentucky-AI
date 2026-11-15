"""Large sheets are detected tile by tile and merged: every symbol found once, including ones cut by tile edges,
and a busy sheet is not limited by the detector's per-pass cap."""

import numpy as np
import torch

from kentucky.training.cv import predict_instances


class BlobDetector(torch.nn.Module):
    """Stand-in detector: boxes every dark blob in the image it is given (like a perfect model), capped per pass."""

    def __init__(self, cap):
        super().__init__()
        self.cap = cap

    def forward(self, images):
        import cv2

        out = []
        for im in images:
            a = ((im[0].numpy() * 0.5 + 0.5) < 0.5).astype(np.uint8)
            n, _, st, _ = cv2.connectedComponentsWithStats(a, connectivity=8)
            b = [[x, y, x + w, y + h] for x, y, w, h, _ in st[1:]][: self.cap]
            out.append({'boxes': torch.tensor(b, dtype=torch.float32).reshape(-1, 4), 'labels': torch.ones(len(b), dtype=torch.int64),
                        'scores': torch.full((len(b),), 0.9)})
        return out


def _sheet():
    g = np.full((1500, 2000), 255, np.uint8)
    boxes = []
    for i in range(60):  # 10 x 6 grid of 16 px symbols; several straddle the 480-px tile stride
        x, y = 70 + (i % 10) * 190, 60 + (i // 10) * 235
        g[y:y + 16, x:x + 16] = 0
        boxes.append((x, y))
    for x, y in ((632, 400), (400, 632), (1112, 1112), (1952, 1352)):  # cut by tile edges at 640 / 1120
        g[y:y + 16, x:x + 16] = 0
        boxes.append((x, y))
    return g, boxes


def test_tiled_detection_finds_each_symbol_once():
    g, truth = _sheet()
    det = BlobDetector(cap=200)
    res = predict_instances(det, g, score_thr=0.5, classes=['door'], tile=640, with_masks=False)
    assert len(res) == len(truth)
    found = sorted((round(r['box'][0]), round(r['box'][1])) for r in res)
    assert found == sorted(truth)
    assert all(r['polygon'] and 'mask' not in r for r in res)


def test_busy_sheet_is_not_capped_by_one_pass():
    g, truth = _sheet()
    capped = BlobDetector(cap=25)
    assert len(predict_instances(capped, g, 0.5, ['door'])) == 25  # one pass: capped
    assert len(predict_instances(capped, g, 0.5, ['door'], tile=640)) == len(truth)  # tiles: all found


class WithStrayBox(BlobDetector):
    """Adds one wrong, low-confidence box covering a whole region in every tile."""

    def forward(self, images):
        out = super().forward(images)
        for o, im in zip(out, images):
            H, W = im.shape[-2:]
            o['boxes'] = torch.cat([o['boxes'], torch.tensor([[0.0, 0.0, W - 1.0, H - 1.0]])])
            o['labels'] = torch.cat([o['labels'], torch.ones(1, dtype=torch.int64)])
            o['scores'] = torch.cat([o['scores'], torch.tensor([0.3])])
        return out


def test_stray_big_box_does_not_swallow_symbols():
    g, truth = _sheet()
    res = predict_instances(WithStrayBox(cap=200), g, score_thr=0.5, classes=['door'], tile=640, with_masks=False)
    assert len(res) == len(truth)
