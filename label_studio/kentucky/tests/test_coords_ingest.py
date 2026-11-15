"""Coordinate round-trips (incl. real PDF render alignment) and ingestion validation."""

import io

import numpy as np
import pytest

from kentucky import coords
from kentucky.ingest.pipeline import IngestError, sniff
from kentucky.samples import synthetic as syn


@pytest.mark.parametrize('rot', [0, 90, 180, 270])
def test_pdf_transform_roundtrip_and_render_alignment(rot):
    import pypdfium2 as pdfium

    plan = syn.generate_plan(7)
    M = coords.pdf_source_to_image(plan.width, plan.height, rot, 2.0)
    pts = np.array([[0, 0], [plan.width, plan.height], [123.4, 56.7]])
    back = coords.apply(coords.invert(M), coords.apply(M, pts))
    assert np.allclose(back, pts, atol=1e-9)
    # every GT line midpoint maps onto ink in the real pdfium render
    img = np.asarray(pdfium.PdfDocument(syn.to_pdf(plan, rot))[0].render(scale=2.0).to_pil().convert('L'))
    lines = [p for p in plan.prims if p.kind == 'line']
    hits = 0
    for p in lines:
        x, y = coords.apply(M, [np.mean(p.pts, axis=0)])[0]
        hits += img[int(round(y)) - 1:int(round(y)) + 2, int(round(x)) - 1:int(round(x)) + 2].min() < 128
    assert hits == len(lines)


def test_extracted_primitives_land_on_source_geometry():
    from kentucky.ingest.extract import extract_pdf

    plan = syn.generate_plan(8)
    ex = extract_pdf(syn.to_pdf(plan, 90))[0]
    gt = np.array([pt for p in plan.prims if p.kind == 'line' for pt in p.pts])
    for pr in [p for p in ex.primitives if p['type'] == 'line'][:50]:
        for q in pr['pts']:  # stored source coords == unrotated page space == plan space
            assert np.min(np.linalg.norm(gt - np.asarray(q), axis=1)) < 0.01
        # stored pixel coords agree with the stored transform
        assert np.allclose(coords.apply(ex.source_to_image, pr['pts']), pr['pts_px'], atol=1e-2)


def test_cad_tile_and_ls_percent_roundtrips():
    M = coords.cad_source_to_image(-50, 10, 950, 610, 2.4, 40)
    p = np.array([[-50, 610], [950, 10], [300.5, 222.2]])
    out = coords.apply(M, p)
    assert np.allclose(out[0], [40, 40]) and np.allclose(coords.apply(coords.invert(M), out), p)
    for x, y, lvl in [(0, 0, 0), (1500.5, 777.25, 0), (1500.5, 777.25, 2), (4095, 3071, 3)]:
        assert np.allclose(coords.tile_to_image(coords.image_to_tile(x, y, lvl)), (x, y))
    poly = [[10, 20], [300.5, 40.25], [150, 199.9]]
    assert np.allclose(coords.ls_percent_to_image(coords.image_to_ls_percent(poly, 640, 480), 640, 480), poly)
    frame = coords.SheetFrame(M, 2400, 1500)
    pred_train = frame.image_to_training(out, 0.5)
    assert np.allclose(frame.prediction_to_source(pred_train, 0.5), p)


@pytest.mark.parametrize('name,data,msg', [
    ('a.dwg', b'AC1032', 'DWG is not natively supported'),
    ('a.ifc', b'ISO-10303-21;', 'IFC is not supported'),
    ('a.exe', b'MZ', 'Unsupported file type'),
    ('a.pdf', b'GIF89a', 'does not look like a PDF'),
    ('a.pdf', b'%PDF-1.4\n/Encrypt 5 0 R', 'Encrypted'),
    ('a.pdf', b'%PDF-1.4\n/OpenAction << /S /JavaScript >>', 'active content'),
    ('a.png', b'\xff\xd8\xff', 'does not look like a PNG'),
    ('a.dxf', b'AutoCAD Binary DXF\r\n', 'Binary DXF'),
    ('a.pdf', b'', 'Empty file'),
])
def test_sniff_rejects_unsafe_or_unsupported(name, data, msg):
    with pytest.raises(IngestError, match=msg):
        sniff(name, data)


def test_dxf_and_scan_extraction():
    from kentucky.ingest.extract import extract_dxf, extract_image

    plan = syn.generate_plan(9)
    dx = extract_dxf(syn.to_dxf(plan))[0]
    assert dx.has_vector and {'A-WALL', 'A-DOOR', 'A-GLAZ', 'A-ANNO'} <= set(dx.metadata['layers'])
    assert sum(1 for p in dx.primitives if p['type'] == 'arc') == sum(1 for p in plan.prims if p.kind == 'curve')
    buf = io.BytesIO()
    syn.to_raster(plan, 2.0, scanned=True, seed=1).save(buf, 'PNG')
    sc = extract_image(buf.getvalue())[0]
    assert not sc.has_vector and sc.vector_provenance == 'raster_inferred'
    lines = [p for p in sc.primitives if p['type'] == 'line']
    assert len(lines) > 50 and all(p['provenance'] == 'raster_inferred' for p in lines)
