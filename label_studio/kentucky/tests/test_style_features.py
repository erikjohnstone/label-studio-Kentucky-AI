"""Line style and CAD layer reach the line-by-line models: PDF dash patterns and DXF linetypes are extracted, the
layer's discipline (M-, P-, E- ...) and name words become features, and models trained before keep working."""

import io

import ezdxf

from kentucky.graph.builder import DISCIPLINES, MODEL_NODE_DIM, NODE_DIM, build_graph, style_features
from kentucky.ingest.extract import extract_dxf, extract_pdf
from kentucky.samples import synthetic as syn


def _disc(f):
    return DISCIPLINES[f[1:1 + len(DISCIPLINES)].index(1.0)]


def test_layer_discipline_and_words():
    assert _disc(style_features({'layer': 'M-DUCT-SUPP'})) == 'M'
    assert _disc(style_features({'layer': 'P-DOMW-HOTW'})) == 'P'
    assert _disc(style_features({'layer': 'E_POWR'})) == 'E'
    assert _disc(style_features({'layer': 'Ductwork'})) == 'other'
    assert _disc(style_features({'layer': '0'})) == 'none' and _disc(style_features({})) == 'none'
    a, b = style_features({'layer': 'M-DUCT'}), style_features({'layer': 'X-DUCT'})
    assert a[1 + len(DISCIPLINES):] == b[1 + len(DISCIPLINES):]  # same word, same hashed slot across firms
    assert style_features({'dashed': True})[0] == 1.0


def test_pdf_dash_pattern_is_extracted_and_used():
    plan = syn.Plan(width=400, height=300)
    plan.prims += [syn.Prim('line', [[50, 50], [350, 50]], 'pipe', 'o1', dash=(6, 3)), syn.Prim('line', [[50, 150], [350, 150]], 'wall', 'o2')]
    ex = extract_pdf(syn.to_pdf(plan))[0]
    lines = sorted((p for p in ex.primitives if p['type'] == 'line'), key=lambda p: p['pts'][0][1])
    assert lines[0].get('dash') == [6.0, 3.0] and not lines[1].get('dash')
    g = build_graph(ex.primitives, ex.image.size)
    assert sorted(n['dashed'] for n in g['nodes']) == [False, True]


def test_dxf_linetype_bylayer_is_resolved():
    doc = ezdxf.new('R2010', setup=True)
    doc.layers.add('P-SANR', linetype='DASHED')
    doc.layers.add('A-WALL')
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={'layer': 'P-SANR'})  # linetype BYLAYER -> DASHED
    msp.add_line((0, 50), (100, 50), dxfattribs={'layer': 'A-WALL'})
    buf = io.StringIO()
    doc.write(buf)
    ex = extract_dxf(buf.getvalue().encode())[0]
    by_layer = {p['layer']: p for p in ex.primitives if p['type'] == 'line'}
    assert by_layer['P-SANR']['linetype'].upper() == 'DASHED' and by_layer['P-SANR']['dash']
    assert not by_layer['A-WALL'].get('dash')
    g = build_graph(ex.primitives, ex.image.size)
    f = {n['layer']: style_features(n) for n in g['nodes']}
    assert f['P-SANR'][0] == 1.0 and _disc(f['P-SANR']) == 'P' and _disc(f['A-WALL']) == 'A'


def test_model_input_appends_style_after_stored_features():
    from kentucky.datasets.export import graph_to_pyg

    g = {'nodes': [{'id': 'a', 'features': [0.5] * NODE_DIM, 'layer': 'M-DUCT', 'dashed': True}], 'edges': []}
    x = graph_to_pyg(g, [], [], require_verified=False).x
    assert x.shape == (1, MODEL_NODE_DIM) and x[0, :NODE_DIM].tolist() == [0.5] * NODE_DIM  # v1 models read these
