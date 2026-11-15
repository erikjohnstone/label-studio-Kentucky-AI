"""Format-specific extraction: PDF (vector + raster), DXF, PNG/JPG.

All extractors return a ``SheetExtract`` per page/layout with:
* ``image`` (PIL) - the annotation-ready render
* ``source_to_image`` - 3x3 affine (kentucky.coords)
* ``primitives`` - list of dicts in the canonical primitive schema (see DATASET_SCHEMA.md)
* ``has_vector`` / ``vector_provenance`` - native CAD/PDF vectors vs raster-inferred lines

Libraries: pdfplumber/pdfminer.six (MIT), pypdfium2/PDFium (Apache-2.0/BSD), ezdxf (MIT),
OpenCV (Apache-2.0), RapidOCR (Apache-2.0, optional). PyMuPDF (AGPL) is deliberately NOT used.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .. import coords

MAX_RENDER_PX = 4096  # longest side of rendered sheet
TARGET_RENDER_PX = 2400
Image.MAX_IMAGE_PIXELS = 120_000_000  # decompression-bomb guard


@dataclass
class SheetExtract:
    page_index: int
    name: str
    image: Image.Image
    source_to_image: np.ndarray
    source_units: str
    rotation: int = 0
    primitives: list = field(default_factory=list)
    has_vector: bool = False
    vector_provenance: str = 'import'
    ocr_status: str = 'not_needed'
    metadata: dict = field(default_factory=dict)


def _bbox_px(pts_px):
    a = np.asarray(pts_px, dtype=float)
    return [float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())]


def _prim(pid, ptype, pts_src, M, **extra):
    pts_px = coords.apply(M, pts_src).round(3).tolist()
    d = {
        'id': pid,
        'type': ptype,
        'pts': [[round(float(x), 4), round(float(y), 4)] for x, y in pts_src],
        'pts_px': pts_px,
        'bbox': [round(v, 3) for v in _bbox_px(pts_px)],
    }
    d.update({k: v for k, v in extra.items() if v is not None})
    return d


# ------------------------------------------------------------------------------------------ PDF
def _render_scale(w_pt, h_pt):
    return min(MAX_RENDER_PX / max(w_pt, h_pt), max(TARGET_RENDER_PX / max(w_pt, h_pt), 1.0))


def _color(c):
    if c is None:
        return None
    if isinstance(c, (int, float)):
        return [float(c)]
    try:
        return [round(float(v), 3) for v in c]
    except TypeError:
        return None


def extract_pdf(data: bytes, max_pages: int = 50):
    import pdfplumber
    import pypdfium2 as pdfium

    pdf_doc = pdfium.PdfDocument(data)
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if len(pdf.pages) > max_pages:
            raise ValueError(f'PDF has {len(pdf.pages)} pages; limit is {max_pages}')
        for i, page in enumerate(pdf.pages):
            rot = int(page.rotation or 0) % 360
            # unrotated page size
            w_disp, h_disp = float(page.width), float(page.height)
            w_src, h_src = (h_disp, w_disp) if rot in (90, 270) else (w_disp, h_disp)
            s = _render_scale(w_src, h_src)
            M = coords.pdf_source_to_image(w_src, h_src, rot, s)
            disp_to_src = coords.invert(coords.pdf_source_to_image(w_src, h_src, rot, 1.0))
            pg = pdf_doc[i]
            image = pg.render(scale=s).to_pil().convert('RGB')

            def src(points):
                return coords.apply(disp_to_src, points).tolist()

            prims = []
            n = 0
            for ln in page.lines:
                pts = ln.get('pts') or [(ln['x0'], ln['top']), (ln['x1'], ln['bottom'])]
                prims.append(_prim(f'p{n}', 'line', src(pts), M, width=ln.get('linewidth'), color=_color(ln.get('stroking_color'))))
                n += 1
            for cv in page.curves:
                pts = cv.get('pts') or []
                if len(pts) < 2:
                    continue
                prims.append(_prim(f'p{n}', 'curve', src(pts), M, width=cv.get('linewidth'),
                                   color=_color(cv.get('stroking_color')), closed=bool(cv.get('fill'))))
                n += 1
            for rc in page.rects:
                pts = [(rc['x0'], rc['top']), (rc['x1'], rc['top']), (rc['x1'], rc['bottom']), (rc['x0'], rc['bottom'])]
                prims.append(_prim(f'p{n}', 'rect', src(pts), M, width=rc.get('linewidth'), closed=True,
                                   color=_color(rc.get('stroking_color'))))
                n += 1
            words = page.extract_words(keep_blank_chars=True, use_text_flow=False, extra_attrs=['size'])
            for w in words:
                pts = [(w['x0'], w['top']), (w['x1'], w['top']), (w['x1'], w['bottom']), (w['x0'], w['bottom'])]
                prims.append(_prim(f'p{n}', 'text', src(pts), M, text=w['text'], size=round(float(w.get('size', 0)), 2)))
                n += 1
            vector_count = len(page.lines) + len(page.curves) + len(page.rects)
            image_area = sum(float(im['width']) * float(im['height']) for im in page.images)
            raster_like = vector_count < 10 and image_area > 0.5 * w_disp * h_disp
            ex = SheetExtract(
                page_index=i, name=f'Page {i + 1}', image=image, source_to_image=M, source_units='pt', rotation=rot,
                primitives=prims, has_vector=not raster_like and vector_count > 0, vector_provenance='import',
                metadata={'page_pt': [w_src, h_src], 'render_scale': s, 'vector_count': vector_count,
                          'word_count': len(words), 'image_area_ratio': image_area / max(w_disp * h_disp, 1)},
            )
            if raster_like:
                _raster_fallback(ex)
            out.append(ex)
    return out


# ------------------------------------------------------------------------------------------ raster
def vectorize_raster(gray: np.ndarray, min_len_px: float = 12.0):
    """Line-segment detection on a scanned plan. Output lines are RASTER-INFERRED, not CAD truth."""
    import cv2

    g = gray if gray.dtype == np.uint8 else gray.astype(np.uint8)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    lines = lsd.detect(bw)[0]
    segs = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            if math.hypot(x2 - x1, y2 - y1) >= min_len_px:
                segs.append([[float(x1), float(y1)], [float(x2), float(y2)]])
    return _merge_parallel_edges(segs)


def _merge_parallel_edges(segs, dist_px=3.5, ang_deg=4.0):
    """LSD returns both edges of each drawn stroke; collapse near-coincident parallel pairs to centerlines."""
    if not segs:
        return []
    arr = np.asarray(segs, dtype=float)
    used = np.zeros(len(arr), bool)
    mids = arr.mean(axis=1)
    vec = arr[:, 1] - arr[:, 0]
    ang = np.degrees(np.arctan2(vec[:, 1], vec[:, 0])) % 180
    out = []
    for i in range(len(arr)):
        if used[i]:
            continue
        used[i] = True
        group = [arr[i]]
        d = vec[i] / (np.linalg.norm(vec[i]) + 1e-9)
        nrm = np.array([-d[1], d[0]])
        for j in np.where(~used)[0]:
            da = abs(ang[i] - ang[j])
            if min(da, 180 - da) > ang_deg:
                continue
            off = abs(np.dot(mids[j] - mids[i], nrm))
            along = abs(np.dot(mids[j] - mids[i], d))
            L = np.linalg.norm(vec[i]) / 2 + np.linalg.norm(vec[j]) / 2
            if off <= dist_px and along <= L:
                used[j] = True
                group.append(arr[j] if np.dot(vec[j], d) >= 0 else arr[j][::-1])
        g = np.asarray(group)
        proj = np.concatenate([g[:, 0] @ d, g[:, 1] @ d])
        c = g.reshape(-1, 2).mean(axis=0)
        t0, t1 = proj.min() - c @ d, proj.max() - c @ d
        out.append([(c + d * t0).tolist(), (c + d * t1).tolist()])
    return out


def ocr_words(image: Image.Image):
    """OCR via RapidOCR (Apache-2.0, ONNX). Returns ([(text, quad_px, score)], status)."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:  # noqa: BLE001
        return [], 'unavailable'
    engine = _OCR.get('engine') or RapidOCR()
    _OCR['engine'] = engine
    result, _ = engine(np.asarray(image.convert('RGB')))
    words = [(txt, [list(map(float, p)) for p in quad], float(score)) for quad, txt, score in (result or [])]
    return words, 'done'


_OCR: dict = {}


def _raster_fallback(ex: SheetExtract, run_ocr: bool = True):
    gray = np.asarray(ex.image.convert('L'))
    inv = coords.invert(ex.source_to_image)
    segs = vectorize_raster(gray)
    base = len(ex.primitives)
    for k, (a, b) in enumerate(segs):
        src = coords.apply(inv, [a, b]).tolist()
        ex.primitives.append(_prim(f'r{base + k}', 'line', src, ex.source_to_image, provenance='raster_inferred'))
    if run_ocr and not any(p['type'] == 'text' for p in ex.primitives):
        words, status = ocr_words(ex.image)
        ex.ocr_status = status
        for k, (txt, quad, score) in enumerate(words):
            src = coords.apply(inv, quad).tolist()
            ex.primitives.append(_prim(f'o{k}', 'text', src, ex.source_to_image, text=txt, ocr_confidence=round(score, 3),
                                       provenance='ocr'))
    ex.has_vector = False
    ex.vector_provenance = 'raster_inferred'
    ex.metadata['raster_inferred_lines'] = len(segs)


def extract_image(data: bytes):
    img = Image.open(io.BytesIO(data))
    img.load()
    img = img.convert('RGB')
    s = min(1.0, MAX_RENDER_PX / max(img.size))
    if s < 1.0:
        img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    M = coords.scale(s)
    ex = SheetExtract(page_index=0, name='Image', image=img, source_to_image=M, source_units='px',
                      metadata={'original_size': list(Image.open(io.BytesIO(data)).size)})
    _raster_fallback(ex)
    return [ex]


# ------------------------------------------------------------------------------------------ DXF
def extract_dxf(data: bytes, max_entities: int = 200_000):
    import ezdxf
    from ezdxf import bbox as ezbbox

    doc = ezdxf.read(io.StringIO(data.decode('utf-8', errors='replace')))
    msp = doc.modelspace()
    ents = list(msp)
    if len(ents) > max_entities:
        raise ValueError('DXF exceeds entity limit')
    ext = ezbbox.extents(msp, fast=True)
    if not ext.has_data:
        raise ValueError('DXF has no drawable geometry')
    (x0, y0, _), (x1, y1, _) = ext.extmin, ext.extmax
    span = max(x1 - x0, y1 - y0, 1e-9)
    margin = 40
    s = (TARGET_RENDER_PX - 2 * margin) / span
    M = coords.cad_source_to_image(x0, y0, x1, y1, s, margin)
    W, H = int((x1 - x0) * s + 2 * margin), int((y1 - y0) * s + 2 * margin)
    prims = []
    n = [0]

    def add(ptype, pts, e, block=None, **kw):
        prims.append(_prim(
            f'p{n[0]}', ptype, pts, M, layer=e.dxf.get('layer', '0'), color=e.dxf.get('color', 256),
            linetype=e.dxf.get('linetype', 'BYLAYER'), handle=e.dxf.get('handle'), block=block, **kw,
        ))
        n[0] += 1

    def visit(e, block=None):
        t = e.dxftype()
        if t == 'LINE':
            add('line', [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)], e, block)
        elif t in ('LWPOLYLINE', 'POLYLINE'):
            pts = [(p[0], p[1]) for p in (e.get_points('xy') if t == 'LWPOLYLINE' else [v.dxf.location for v in e.vertices])]
            closed = bool(e.closed if t == 'LWPOLYLINE' else e.is_closed)
            if len(pts) >= 2:
                add('polyline', pts + ([pts[0]] if closed else []), e, block, closed=closed)
        elif t == 'ARC':
            c, r = e.dxf.center, e.dxf.radius
            a0, a1 = e.dxf.start_angle, e.dxf.end_angle
            if a1 < a0:
                a1 += 360
            angs = np.radians(np.linspace(a0, a1, max(8, int((a1 - a0) / 6))))
            add('arc', [(c.x + r * math.cos(a), c.y + r * math.sin(a)) for a in angs], e, block,
                center=[c.x, c.y], radius=r, start_angle=a0, end_angle=a1 % 360)
        elif t == 'CIRCLE':
            c, r = e.dxf.center, e.dxf.radius
            angs = np.radians(np.linspace(0, 360, 33))
            add('circle', [(c.x + r * math.cos(a), c.y + r * math.sin(a)) for a in angs], e, block,
                center=[c.x, c.y], radius=r, closed=True)
        elif t in ('TEXT', 'MTEXT'):
            txt = e.dxf.text if t == 'TEXT' else e.plain_text()
            ins = e.dxf.insert
            h = float(e.dxf.get('height', 0) or e.dxf.get('char_height', 2.5) or 2.5)
            wdt = max(len(txt), 1) * h * 0.6
            add('text', [(ins.x, ins.y + h), (ins.x + wdt, ins.y + h), (ins.x + wdt, ins.y), (ins.x, ins.y)], e, block,
                text=txt, size=h)
        elif t == 'SPLINE':
            pts = [(p.x, p.y) for p in e.flattening(0.01 * span)]
            if len(pts) >= 2:
                add('curve', pts, e, block)
        elif t == 'INSERT':
            for ve in e.virtual_entities():
                visit(ve, block=e.dxf.name)

    for e in ents:
        try:
            visit(e)
        except Exception:  # noqa: BLE001 - skip unsupported/corrupt entities but keep going
            continue
    image = _draw_prims((W, H), prims)
    return [SheetExtract(
        page_index=0, name='Model space', image=image, source_to_image=M, source_units='cad_units', primitives=prims,
        has_vector=True, vector_provenance='import',
        metadata={'extents': [x0, y0, x1, y1], 'px_per_unit': s, 'insunits': doc.header.get('$INSUNITS', 0),
                  'layers': sorted({p.get('layer', '0') for p in prims})},
    )]


def _draw_prims(size, prims):
    from PIL import ImageDraw

    img = Image.new('RGB', size, 'white')
    d = ImageDraw.Draw(img)
    for p in prims:
        pts = [tuple(q) for q in p['pts_px']]
        if p['type'] == 'text':
            d.text((pts[0][0], pts[0][1]), p.get('text', ''), fill='black')
        elif len(pts) >= 2:
            d.line(pts, fill='black', width=2)
    return img
