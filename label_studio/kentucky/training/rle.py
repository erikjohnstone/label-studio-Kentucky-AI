"""COCO uncompressed RLE helpers (Django-free)."""

import numpy as np


def rle_encode(mask: np.ndarray) -> dict:
    """COCO uncompressed RLE (column-major)."""
    flat = np.asarray(mask, dtype=np.uint8).flatten(order='F')
    counts = []
    prev, run = 0, 0
    for v in flat:
        if v != prev:
            counts.append(run)
            run, prev = 0, v
        run += 1
    counts.append(run)
    return {'size': [int(mask.shape[0]), int(mask.shape[1])], 'counts': counts}


def rle_decode(rle: dict) -> np.ndarray:
    h, w = rle['size']
    flat = np.zeros(h * w, dtype=np.uint8)
    pos, val = 0, 0
    for c in rle['counts']:
        flat[pos:pos + c] = val
        pos += c
        val = 1 - val
    return flat.reshape((h, w), order='F')
