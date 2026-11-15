"""Coordinate systems and transforms for construction drawings.

Every sheet carries one affine transform ``source -> image`` stored as a 3x3 matrix
(row-major nested lists). All other spaces are derived from it:

* ``source``     PDF: unrotated page space in points, origin top-left, y down
                 (the convention pdfplumber/pdfminer objects use after ``top`` conversion).
                 DXF: CAD model units, origin at drawing extents min, y UP.
                 Raster: identity (source == image pixels).
* ``image``      pixels of the rendered sheet image (what annotators see), origin top-left, y down.
* ``tile``       (level, col, row, local_x, local_y) of the image pyramid; level 0 is full resolution,
                 level L is downsampled by 2**L.
* ``annotation`` Label Studio stores percentages of the image (0-100).
* ``training``   image pixels of the (optionally resized) training sample: image * training_scale.
* ``prediction`` the model's output pixels; mapped back via the training scale.

Round-trip tests live in ``kentucky/tests/test_coords.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

TILE_SIZE = 512


def identity() -> np.ndarray:
    return np.eye(3)


def scale(sx: float, sy: float | None = None) -> np.ndarray:
    sy = sx if sy is None else sy
    return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1.0]])


def translate(tx: float, ty: float) -> np.ndarray:
    return np.array([[1.0, 0, tx], [0, 1.0, ty], [0, 0, 1.0]])


def pdf_source_to_image(page_width_pt: float, page_height_pt: float, rotation: int, render_scale: float) -> np.ndarray:
    """Matrix from unrotated top-left PDF points to pixels of the page rendered with its /Rotate applied.

    ``rotation`` is the page /Rotate value (clockwise degrees, multiple of 90). pdfium renders
    the page rotated clockwise by that amount, which is what we reproduce here.
    """
    rotation = int(rotation) % 360
    w, h = page_width_pt, page_height_pt
    if rotation == 0:
        rot = identity()
    elif rotation == 90:  # (x, y) -> (h - y, x)
        rot = np.array([[0, -1.0, h], [1.0, 0, 0], [0, 0, 1.0]])
    elif rotation == 180:  # (x, y) -> (w - x, h - y)
        rot = np.array([[-1.0, 0, w], [0, -1.0, h], [0, 0, 1.0]])
    elif rotation == 270:  # (x, y) -> (y, w - x)
        rot = np.array([[0, 1.0, 0], [-1.0, 0, w], [0, 0, 1.0]])
    else:
        raise ValueError(f'Unsupported page rotation {rotation}')
    return scale(render_scale) @ rot


def cad_source_to_image(min_x: float, min_y: float, max_x: float, max_y: float, px_per_unit: float, margin_px: float = 0) -> np.ndarray:
    """Matrix from CAD model space (y up) to image pixels (y down) fitting the extents."""
    if max_x < min_x or max_y < min_y:
        raise ValueError('Invalid CAD extents')
    # x' = (x - min_x) * s + m ; y' = (max_y - y) * s + m
    s = px_per_unit
    return translate(margin_px, margin_px) @ np.array([[s, 0, -min_x * s], [0, -s, max_y * s], [0, 0, 1.0]])


def apply(m: np.ndarray | Sequence[Sequence[float]], points: Iterable[Sequence[float]]) -> np.ndarray:
    m = np.asarray(m, dtype=float)
    pts = np.asarray(list(points), dtype=float).reshape(-1, 2)
    homo = np.hstack([pts, np.ones((len(pts), 1))])
    out = homo @ m.T
    return out[:, :2]


def invert(m) -> np.ndarray:
    return np.linalg.inv(np.asarray(m, dtype=float))


def to_list(m) -> list:
    return np.asarray(m, dtype=float).round(12).tolist()


def unit_scale(m) -> float:
    """Average linear scale factor of an affine matrix (pixels per source unit)."""
    m = np.asarray(m, dtype=float)
    return float(math.sqrt(abs(np.linalg.det(m[:2, :2]))))


# ---------------------------------------------------------------- Label Studio percent space
def image_to_ls_percent(points, width: int, height: int) -> list[list[float]]:
    return [[x / width * 100.0, y / height * 100.0] for x, y in points]


def ls_percent_to_image(points, width: int, height: int) -> list[list[float]]:
    return [[x * width / 100.0, y * height / 100.0] for x, y in points]


# ---------------------------------------------------------------- tiles
@dataclass(frozen=True)
class TileCoord:
    level: int
    col: int
    row: int
    x: float
    y: float


def image_to_tile(x: float, y: float, level: int = 0, tile_size: int = TILE_SIZE) -> TileCoord:
    f = 2**level
    lx, ly = x / f, y / f
    col, row = int(lx // tile_size), int(ly // tile_size)
    return TileCoord(level, col, row, lx - col * tile_size, ly - row * tile_size)


def tile_to_image(t: TileCoord, tile_size: int = TILE_SIZE) -> tuple[float, float]:
    f = 2**t.level
    return ((t.col * tile_size + t.x) * f, (t.row * tile_size + t.y) * f)


def pyramid_levels(width: int, height: int, tile_size: int = TILE_SIZE) -> int:
    levels = 1
    while max(width, height) / 2 ** (levels - 1) > tile_size:
        levels += 1
    return levels


# ---------------------------------------------------------------- full chain helper
class SheetFrame:
    """Convenience wrapper around a sheet's stored transform."""

    def __init__(self, source_to_image, width: int, height: int):
        self.m = np.asarray(source_to_image, dtype=float)
        self.inv = invert(self.m)
        self.width, self.height = int(width), int(height)

    def source_to_image(self, pts):
        return apply(self.m, pts)

    def image_to_source(self, pts):
        return apply(self.inv, pts)

    def image_to_training(self, pts, training_scale: float):
        return np.asarray(pts, dtype=float) * training_scale

    def prediction_to_source(self, pts, training_scale: float):
        return self.image_to_source(np.asarray(pts, dtype=float) / training_scale)

    def to_dict(self):
        return {'source_to_image': to_list(self.m), 'width': self.width, 'height': self.height}


def clean_polygon(poly, W=None, H=None):
    """Make an outline usable for training: repair self-crossings (mask tracing produces them), clip to the sheet,
    keep the largest piece. Returns a list of [x, y] or None if nothing usable is left."""
    from shapely.geometry import Polygon, box
    from shapely.validation import make_valid

    if not poly or len(poly) < 3:
        return None
    p = Polygon(poly)
    if p.is_valid and (W is None or (min(x for x, _ in poly) >= -1 and min(y for _, y in poly) >= -1 and max(x for x, _ in poly) <= W + 1 and max(y for _, y in poly) <= H + 1)):
        return [list(map(float, c)) for c in poly]
    g = make_valid(p)
    if W is not None:
        g = g.intersection(box(0, 0, W, H))
    parts = [x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'Polygon' and x.area > 0]
    if not parts:
        return None
    best = max(parts, key=lambda x: x.area).simplify(0.5, preserve_topology=True)
    out = [[float(x), float(y)] for x, y in list(best.exterior.coords)[:-1]]
    return out if len(out) >= 3 else None
