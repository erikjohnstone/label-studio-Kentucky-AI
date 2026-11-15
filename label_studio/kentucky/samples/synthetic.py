"""Synthetic construction floor plans with exact ground truth.

Used for the CPU training fallback, automated end-to-end tests and demos. Generates the *same*
plan as a native vector PDF, a DXF, and a "scanned" raster (blur + noise + optional skew), together
with ground-truth objects (walls, doors, windows, room tags) and per-primitive labels.

Everything is synthetic: no customer drawings are used or distributed.
"""

from __future__ import annotations

import io
import math
import random
import zlib
from dataclasses import dataclass, field

import numpy as np

WALL = 'wall'
DOOR = 'door'
WINDOW = 'window'
TEXT = 'room_tag'
CLASSES_CV = [WALL, DOOR, WINDOW]
NODE_CLASSES = [WALL, DOOR, WINDOW, TEXT]
ROOM_NAMES = ['OFFICE', 'CONF', 'STORAGE', 'LOBBY', 'BREAK', 'MECH', 'ELEC', 'OPEN OFFICE', 'RESTROOM', 'IT']


@dataclass
class Prim:
    kind: str  # line | curve | text
    pts: list  # line: [p0,p1]; curve: [p0,c1,c2,p3]; text: [anchor]
    label: str
    obj: str  # ground-truth object id
    text: str = ''
    width: float = 0.7
    dash: tuple = ()  # PDF dash array in points, () = solid


@dataclass
class Plan:
    width: float  # points
    height: float
    prims: list = field(default_factory=list)
    objects: dict = field(default_factory=dict)  # obj id -> {label, polygon(list of pts)[, length_pt, system]}
    seed: int = 0
    grid: tuple = ()  # (xs, ys) room grid lines


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def generate_plan(seed: int = 0, width: float = 792.0, height: float = 612.0) -> Plan:
    """Generate a rectilinear office floor plan in top-left/y-down point space."""
    rng = random.Random(seed)
    plan = Plan(width=width, height=height, seed=seed)
    m = 60.0
    x0, y0, x1, y1 = m, m, width - m, height - m
    t = rng.choice([6.0, 8.0])  # wall thickness (pt)
    ncols, nrows = rng.randint(2, 4), rng.randint(2, 3)
    xs = sorted([x0, x1] + [x0 + (x1 - x0) * (i + rng.uniform(-0.12, 0.12)) / ncols for i in range(1, ncols)])
    ys = sorted([y0, y1] + [y0 + (y1 - y0) * (j + rng.uniform(-0.12, 0.12)) / nrows for j in range(1, nrows)])
    counter = {'w': 0, 'd': 0, 'n': 0, 't': 0}

    def nid(p):
        counter[p] += 1
        return f'{p}{counter[p]}'

    def wall_run(a, b, horizontal, fixed, exterior):
        """Wall from a to b along an axis, with optional door / window openings."""
        length = b - a
        openings = []
        if length > 70:
            if exterior and rng.random() < 0.8:
                c = rng.uniform(a + 25, b - 25)
                w = rng.uniform(24, 36)
                openings.append(('window', c - w / 2, c + w / 2))
            elif not exterior:
                c = rng.uniform(a + 22, b - 22)
                w = 30.0
                openings.append(('door', c - w / 2, c + w / 2))
        cuts = [a] + [v for o in openings for v in (o[1], o[2])] + [b]
        segs = [(cuts[i], cuts[i + 1]) for i in range(0, len(cuts), 2)]
        h = t / 2
        for s0, s1 in segs:
            oid = nid('w')
            if horizontal:
                poly = _rect(s0, fixed - h, s1, fixed + h)
                lines = [[[s0, fixed - h], [s1, fixed - h]], [[s0, fixed + h], [s1, fixed + h]]]
            else:
                poly = _rect(fixed - h, s0, fixed + h, s1)
                lines = [[[fixed - h, s0], [fixed - h, s1]], [[fixed + h, s0], [fixed + h, s1]]]
            plan.objects[oid] = {'label': WALL, 'polygon': poly}
            for ln in lines:
                plan.prims.append(Prim('line', ln, WALL, oid))
            # end caps close the wall at openings
            for s in (s0, s1):
                cap = [[s, fixed - h], [s, fixed + h]] if horizontal else [[fixed - h, s], [fixed + h, s]]
                plan.prims.append(Prim('line', cap, WALL, oid))
        for kind, o0, o1 in openings:
            if kind == 'window':
                oid = nid('n')
                poly = _rect(o0, fixed - h, o1, fixed + h) if horizontal else _rect(fixed - h, o0, fixed + h, o1)
                plan.objects[oid] = {'label': WINDOW, 'polygon': poly}
                for off in (-h, 0.0, h):
                    ln = [[o0, fixed + off], [o1, fixed + off]] if horizontal else [[fixed + off, o0], [fixed + off, o1]]
                    plan.prims.append(Prim('line', ln, WINDOW, oid, width=0.35))
            else:
                oid = nid('d')
                r = o1 - o0
                sgn = rng.choice([-1, 1])
                k = 0.5523 * r
                if horizontal:
                    hinge = [o0, fixed]
                    tip = [o0, fixed + sgn * r]
                    end = [o1, fixed]
                    curve = [tip, [o0 + k, fixed + sgn * r], [o1, fixed + sgn * k], end]
                    ys_ = sorted([fixed, fixed + sgn * r])
                    poly = _rect(o0, ys_[0], o1, ys_[1])
                else:
                    hinge = [fixed, o0]
                    tip = [fixed + sgn * r, o0]
                    end = [fixed, o1]
                    curve = [tip, [fixed + sgn * r, o0 + k], [fixed + sgn * k, o1], end]
                    xs_ = sorted([fixed, fixed + sgn * r])
                    poly = _rect(xs_[0], o0, xs_[1], o1)
                plan.objects[oid] = {'label': DOOR, 'polygon': poly}
                plan.prims.append(Prim('line', [hinge, tip], DOOR, oid, width=0.5))
                plan.prims.append(Prim('curve', curve, DOOR, oid, width=0.35))

    for j, y in enumerate(ys):
        ext = j in (0, len(ys) - 1)
        for i in range(len(xs) - 1):
            wall_run(xs[i], xs[i + 1], True, y, ext)
    for i, x in enumerate(xs):
        ext = i in (0, len(xs) - 1)
        for j in range(len(ys) - 1):
            wall_run(ys[j], ys[j + 1], False, x, ext)
    # room tags
    n = 100
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            n += 1
            name = f'{rng.choice(ROOM_NAMES)} {n}'
            cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
            oid = nid('t')
            tw = len(name) * 4.4
            plan.objects[oid] = {'label': TEXT, 'polygon': _rect(cx - tw / 2, cy - 4, cx + tw / 2, cy + 4)}
            plan.prims.append(Prim('text', [[cx - tw / 2, cy + 3]], TEXT, oid, text=name))
    plan.grid = (xs, ys)
    return plan


# --------------------------------------------------------------------------- writers
def _pdf_escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def to_pdf(plan: Plan, rotate: int = 0) -> bytes:
    """Minimal hand-written PDF 1.4 with vector paths and real text (Helvetica)."""
    H = plan.height
    ops = ['0 0 0 RG 0 0 0 rg']
    for p in plan.prims:
        if p.kind == 'line':
            (ax, ay), (bx, by) = p.pts
            ops.append(f'{p.width:.2f} w {ax:.3f} {H - ay:.3f} m {bx:.3f} {H - by:.3f} l S')
        elif p.kind == 'curve':
            (ax, ay), (c1x, c1y), (c2x, c2y), (bx, by) = p.pts
            ops.append(
                f'{p.width:.2f} w {ax:.3f} {H - ay:.3f} m {c1x:.3f} {H - c1y:.3f} {c2x:.3f} {H - c2y:.3f} '
                f'{bx:.3f} {H - by:.3f} c S'
            )
        elif p.kind == 'text':
            (ax, ay), = p.pts
            ops.append(f'BT /F1 8 Tf {ax:.3f} {H - ay:.3f} Td ({_pdf_escape(p.text)}) Tj ET')
    content = zlib.compress('\n'.join(ops).encode('latin-1'))
    objs = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {plan.width:.3f} {plan.height:.3f}] /Rotate {int(rotate)} '
            '/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>'
        ).encode(),
        b'<< /Length ' + str(len(content)).encode() + b' /Filter /FlateDecode >>\nstream\n' + content + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f'{i} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = out.tell()
    out.write(f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode())
    for off in offsets:
        out.write(f'{off:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return out.getvalue()


def to_dxf(plan: Plan, units_per_pt: float = 1.0) -> bytes:
    """DXF (R2010) with one layer per class. CAD space is y-up."""
    import ezdxf

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    for name, color in [('A-WALL', 7), ('A-DOOR', 3), ('A-GLAZ', 5), ('A-ANNO', 2)]:
        doc.layers.add(name, color=color)
    layer = {WALL: 'A-WALL', DOOR: 'A-DOOR', WINDOW: 'A-GLAZ', TEXT: 'A-ANNO'}
    H = plan.height

    def c(p):
        return (p[0] * units_per_pt, (H - p[1]) * units_per_pt)

    for p in plan.prims:
        attrs = {'layer': layer[p.label]}
        if p.kind == 'line':
            msp.add_line(c(p.pts[0]), c(p.pts[1]), dxfattribs=attrs)
        elif p.kind == 'curve':
            # quarter-circle door swing as a true ARC entity
            p0, _, _, p3 = p.pts
            # hinge is the corner of the swing bbox shared by p3's axis and p0's axis
            hinge = (p0[0], p3[1]) if abs(p0[0] - p3[0]) > 1e-6 and abs(p0[1] - p3[1]) > 1e-6 else p0
            if abs(p0[0] - p3[0]) > 1e-6 and abs(p0[1] - p3[1]) > 1e-6:
                cands = [(p0[0], p3[1]), (p3[0], p0[1])]
                hinge = min(cands, key=lambda h: abs(math.dist(h, p0) - math.dist(h, p3)))
            hc = c(hinge)
            r = math.dist(c(p0), hc)
            a0 = math.degrees(math.atan2(c(p0)[1] - hc[1], c(p0)[0] - hc[0]))
            a1 = math.degrees(math.atan2(c(p3)[1] - hc[1], c(p3)[0] - hc[0]))
            if (a1 - a0) % 360 > 180:
                a0, a1 = a1, a0
            msp.add_arc(hc, r, a0, a1, dxfattribs=attrs)
        elif p.kind == 'text':
            msp.add_text(p.text, height=8 * units_per_pt, dxfattribs=attrs).set_placement(c(p.pts[0]))
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode('utf-8')


def to_raster(plan: Plan, px_per_pt: float = 2.0, scanned: bool = False, seed: int = 0, skew_deg: float = 0.0):
    """Render with PIL. ``scanned`` adds blur, noise, toner speckle and slight skew (no vectors kept)."""
    from PIL import Image, ImageDraw, ImageFilter

    W, H = int(plan.width * px_per_pt), int(plan.height * px_per_pt)
    img = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(img)
    s = px_per_pt
    for p in plan.prims:
        w = max(1, int(round(p.width * s * 1.4)))
        if p.kind == 'line':
            d.line([tuple(np.multiply(p.pts[0], s)), tuple(np.multiply(p.pts[1], s))], fill=0, width=w)
        elif p.kind == 'curve':
            p0, c1, c2, p3 = [np.array(q) * s for q in p.pts]
            ts = np.linspace(0, 1, 24)
            pts = [tuple((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t**2 * c2 + t**3 * p3) for t in ts]
            d.line(pts, fill=0, width=w)
        elif p.kind == 'text':
            x, y = np.multiply(p.pts[0], s)
            d.text((x, y - 9 * s), p.text, fill=0)
    if scanned:
        rng = np.random.default_rng(seed)
        if skew_deg:
            img = img.rotate(skew_deg, resample=Image.BILINEAR, fillcolor=255)
        img = img.filter(ImageFilter.GaussianBlur(0.8))
        a = np.asarray(img, dtype=np.float32)
        a += rng.normal(0, 12, a.shape)
        speck = rng.random(a.shape) < 0.0015
        a[speck] = 40
        a = (a * 0.92 + 245 * 0.08).clip(0, 255).astype(np.uint8)  # yellowed paper
        img = Image.fromarray(a, 'L')
    return img


def gt_masks(plan: Plan, px_per_pt: float, classes=CLASSES_CV):
    """Semantic mask (H,W uint8; 0=background, i+1=class) and instance list in image px."""
    from PIL import Image, ImageDraw

    W, H = int(plan.width * px_per_pt), int(plan.height * px_per_pt)
    sem = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(sem)
    inst = []
    for oid, o in plan.objects.items():
        if o['label'] not in classes:
            continue
        poly = [(x * px_per_pt, y * px_per_pt) for x, y in o['polygon']]
        d.polygon(poly, fill=classes.index(o['label']) + 1)
        inst.append({'id': oid, 'label': o['label'], 'polygon': [list(p) for p in poly]})
    return np.asarray(sem), inst
