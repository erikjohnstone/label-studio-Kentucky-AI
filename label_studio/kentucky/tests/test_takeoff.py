"""Takeoff math on drawings with known answers: run lengths in feet, double-line ducts counted once, fittings."""

import pytest

from kentucky.takeoff import feet_per_unit, parse_scale, takeoff

FT = 72 * 12 / 96  # PDF points per real foot at 1/8" = 1'-0"  (= 9 pt)


def L(pid, a, b, typ='line'):
    return {'id': pid, 'type': typ, 'pts': [list(a), list(b)]}


@pytest.mark.parametrize('text,ratio', [('1/8" = 1\'-0"', 96), ('SCALE: 1/4" = 1\'-0"', 48), ('3/16"=1\'-0"', 64),
                                        ('1" = 20\'', 240), ('SCALE 1:100', 100), ('1:50', 50), ('ROOM 101', None), ('12x10', None)])
def test_scale_notes(text, ratio):
    assert parse_scale(text) == ratio


def test_pdf_scale_from_sheet_text_and_cad_units():
    prims = [{'id': 't1', 'type': 'text', 'text': 'SCALE:', 'pts': [[500, 700], [530, 700], [530, 708], [500, 708]]},
             {'id': 't2', 'type': 'text', 'text': '1/8"', 'pts': [[533, 700], [548, 700], [548, 708], [533, 708]]},
             {'id': 't3', 'type': 'text', 'text': "=", 'pts': [[550, 700], [554, 700], [554, 708], [550, 708]]},
             {'id': 't4', 'type': 'text', 'text': "1'-0\"", 'pts': [[556, 700], [575, 700], [575, 708], [556, 708]]}]
    f, how = feet_per_unit('pt', {}, prims)
    assert f == pytest.approx(1 / FT) and '1/8' in how
    assert feet_per_unit('cad_units', {'insunits': 1}, [])[0] == pytest.approx(1 / 12)
    assert feet_per_unit('cad_units', {'insunits': 0}, [])[0] is None
    assert feet_per_unit('px', {}, [])[0] is None and feet_per_unit('px', {}, [], override=0.05)[0] == 0.05


def test_pipe_run_length_elbows_and_tee():
    # L-shaped pipe: 40 ft east then 20 ft south, plus a 10 ft branch teeing off the middle of the first leg
    prims = [L('a', (0, 0), (40 * FT, 0)), L('b', (40 * FT, 0), (40 * FT, 20 * FT)), L('c', (20 * FT, 0), (20 * FT, 10 * FT)),
             L('w', (0, 100 * FT), (60 * FT, 100 * FT))]  # an unrelated wall
    r = takeoff(prims, {'a': 'pipe', 'b': 'pipe', 'c': 'pipe', 'w': 'wall'}, 1 / FT)
    pipe = r['systems']['pipe']
    assert pipe['total_length'] == pytest.approx(70.0) and len(pipe['runs']) == 1
    assert pipe['elbows'] == 1 and pipe['tees'] == 1 and pipe['runs'][0]['ends'] == 3  # start, end, branch end
    assert r['units'] == 'ft' and r['systems']['wall']['total_length'] == pytest.approx(60.0)


def test_double_line_duct_is_measured_once_along_its_centerline():
    w = 1.5 * FT  # 18" duct drawn as two lines
    prims = [L('d1', (0, 0), (50 * FT, 0)), L('d2', (0, w), (50 * FT, w)),  # 50 ft straight
             L('d3', (50 * FT, 0), (50 * FT, -30 * FT)), L('d4', (50 * FT + w, w), (50 * FT + w, -30 * FT))]  # turns, 30 ft
    r = takeoff(prims, {p['id']: 'duct' for p in prims}, 1 / FT)
    duct = r['systems']['duct']
    assert duct['double_line'] and duct['total_length'] == pytest.approx(80.75, abs=1.0)  # centerline, not 2x
    assert duct['runs'][0]['segments'] == 2


def test_two_separate_runs_and_no_scale():
    prims = [L('a', (0, 0), (100, 0)), L('b', (0, 50), (100, 50))]
    r = takeoff(prims, {'a': 'conduit', 'b': 'conduit'}, None)
    assert r['units'] == 'drawing units' and len(r['systems']['conduit']['runs']) == 2
    assert r['systems']['conduit']['total_length'] == pytest.approx(200)


@pytest.mark.django_db
def test_takeoff_through_the_platform_matches_drawing_truth(org_a, client_a):
    """Upload a PDF plan, label its lines as an annotator would, ask the API for the takeoff, compare to the truth."""
    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user, name='takeoff')
    plan, _, sheet = F.upload_plan(ds, user, 211, 'pdf')
    F.simulate_graph_labeling(sheet, plan, 'pdf', user)
    truth = sum(max(abs(o['polygon'][2][0] - o['polygon'][0][0]), abs(o['polygon'][2][1] - o['polygon'][0][1]))
                for o in plan.objects.values() if o['label'] == 'wall')  # wall pieces: centerline = long side (pt)
    r = client_a.get(f'/api/ka/sheets/{sheet.id}/takeoff/?feet_per_unit={1 / FT}').json()  # drawn at 1/8" = 1'-0"
    wall = r['systems']['wall']
    assert r['units'] == 'ft' and r['scale_source'] == 'given' and wall['double_line']
    assert wall['total_length'] == pytest.approx(truth / FT, rel=0.02)  # measured: within 1% on 5 plans
    assert client_a.get(f'/api/ka/sheets/{sheet.id}/takeoff/').json()['scale_source'] == 'no scale note found on the sheet'
