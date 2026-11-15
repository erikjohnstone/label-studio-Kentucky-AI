"""Check screen: AI suggestions -> Keep / Dismiss / undo -> autosaved LS annotation -> Done approves the sheet.
Also: unchecked sheets never enter a dataset version, and outlines are repaired before training."""

import pytest


@pytest.mark.django_db
def test_review_keep_dismiss_done(client_a, org_a):
    from kentucky.models import CanonicalObject, Proposal, Provenance, Review
    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user, classes=['wall', 'door', 'window'])
    _, _, sheet = F.upload_plan(ds, user, 41, 'pdf')
    _, _, other = F.upload_plan(ds, user, 42, 'pdf')

    r = client_a.get(f'/api/ka/sheets/{sheet.id}/review/')
    assert r.status_code == 200 and r.data['suggestions'] == [] and r.data['can_find_more']
    r = client_a.post(f'/api/ka/sheets/{sheet.id}/find-more/', {}, format='json')
    assert r.status_code == 200 and r.data['source'] == 'drawing' and r.data['created'] > 3
    d = client_a.get(f'/api/ka/sheets/{sheet.id}/review/').data
    sug = d['suggestions']
    assert len(sug) == r.data['created'] and all(len(s['polygon']) >= 3 for s in sug)

    keep = sug[0]
    relabel = next(x for x in sug[1:] if x['label'] != 'door')
    dismiss = next(x for x in sug[1:] if x['id'] != relabel['id'])
    W, H = sheet.width, sheet.height
    region = lambda s, label: {'id': f'ka{s["id"]}', 'from_name': 'polygonlabels', 'to_name': 'image', 'type': 'polygonlabels',
                               'original_width': W, 'original_height': H, 'image_rotation': 0,
                               'value': {'points': [[x / W * 100, y / H * 100] for x, y in s['polygon']], 'closed': True, 'polygonlabels': [label]}}
    assert client_a.post(f'/api/ka/sheets/{sheet.id}/decide/', {'proposal_id': keep['id'], 'action': 'keep'}, format='json').data['status'] == 'accepted'
    assert client_a.post(f'/api/ka/sheets/{sheet.id}/decide/', {'proposal_id': relabel['id'], 'action': 'keep', 'label': 'door'}, format='json').data['status'] == 'modified'
    assert client_a.post(f'/api/ka/sheets/{sheet.id}/decide/', {'proposal_id': dismiss['id'], 'action': 'dismiss'}, format='json').data['status'] == 'rejected'
    # undo returns it to the queue
    assert client_a.post(f'/api/ka/sheets/{sheet.id}/decide/', {'proposal_id': dismiss['id'], 'action': 'undo'}, format='json').data['status'] == 'pending'
    drawn = {'id': 'u1', 'from_name': 'polygonlabels', 'to_name': 'image', 'type': 'polygonlabels', 'original_width': W, 'original_height': H,
             'value': {'points': [[10, 10], [12, 10], [12, 13], [10, 13]], 'closed': True, 'polygonlabels': ['window']}}
    r = client_a.post(f'/api/ka/sheets/{sheet.id}/markup/', {'result': [region(keep, keep['label']), region(relabel, 'door'), drawn]}, format='json')
    assert r.status_code == 200 and r.data['objects'] == 3

    objs = {o.ls_result_id: o for o in CanonicalObject.objects.filter(sheet=sheet, deleted=False)}
    assert objs[f'ka{keep["id"]}'].provenance == Provenance.AGENT_ACCEPTED and objs[f'ka{keep["id"]}'].proposal_id == keep['id']
    assert objs[f'ka{relabel["id"]}'].label == 'door'
    assert objs['u1'].provenance == Provenance.HUMAN

    # Done with suggestions left -> asks first; with dismiss_rest -> everything left is dismissed and the sheet is approved
    r = client_a.post(f'/api/ka/sheets/{sheet.id}/done/', {}, format='json')
    assert r.data == {'done': False, 'pending': len(sug) - 2}
    r = client_a.post(f'/api/ka/sheets/{sheet.id}/done/', {'dismiss_rest': True}, format='json')
    assert r.data['done'] and r.data['approved'] == 3 and r.data['next'] == other.id
    assert not CanonicalObject.objects.filter(sheet=sheet, deleted=False).exclude(review_status=Review.APPROVED).exists()
    assert not Proposal.objects.filter(sheet=sheet, status='pending').exists()

    home = client_a.get('/api/ka/home/').data
    row = next(x for x in home['plan_sets'] if x['id'] == ds.id)
    assert row['done'] == 1 and {s['id']: s['state'] for s in row['sheets']} == {sheet.id: 'done', other.id: 'empty'}

    # only the checked sheet goes into a version
    from kentucky.datasets.versioning import create_version

    v = create_version(ds, user)
    assert {s['id'] for s in v.manifest['sheets']} == {sheet.id}


@pytest.mark.django_db
def test_review_is_org_scoped(client_b, org_a):
    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user)
    _, _, sheet = F.upload_plan(ds, user, 43, 'pdf')
    for path in ('review/',):
        assert client_b.get(f'/api/ka/sheets/{sheet.id}/{path}').status_code == 404
    for path in ('find-more/', 'done/', 'decide/'):
        assert client_b.post(f'/api/ka/sheets/{sheet.id}/{path}', {}, format='json').status_code == 404


def test_clean_polygon_repairs_self_crossing():
    from shapely.geometry import Polygon

    from kentucky.coords import clean_polygon

    bowtie = [[0, 0], [10, 10], [10, 0], [0, 10]]
    assert not Polygon(bowtie).is_valid
    out = clean_polygon(bowtie, 100, 100)
    assert out and Polygon(out).is_valid
    assert clean_polygon([[0, 0], [5, 0], [5, 5], [0, 5]], 100, 100) == [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]
    clipped = clean_polygon([[-20, -20], [50, -20], [50, 50], [-20, 50]], 30, 30)
    assert max(x for x, _ in clipped) <= 30 and min(y for _, y in clipped) >= 0
