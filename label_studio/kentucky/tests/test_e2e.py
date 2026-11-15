"""End-to-end tests A-D through the HTTP API (real ingestion, labeling records, training, registry, inference).

Training runs real PyTorch / PyG code in a worker subprocess (CPU). Epoch counts are small to keep CI
time reasonable; tests assert real learning signals (loss decreases / scores above chance), never fixed
metric values.
"""

import base64
import io
import time

import numpy as np
import pytest

from kentucky.models import CanonicalObject, JobStatus, ModelVersion, Proposal, SheetGraph
from kentucky.orchestration import service as S
from kentucky.samples import factories as F
from kentucky.samples import synthetic as syn


def _upload(client, ds_id, name, data, group):
    from django.core.files.uploadedfile import SimpleUploadedFile

    r = client.post(f'/api/ka/datasets/{ds_id}/documents/', {'file': SimpleUploadedFile(name, data), 'split_group': group}, format='multipart')
    assert r.status_code == 201, r.content
    res = r.json()[0]
    assert res['status'] == 'ready', res
    return res


def _train(client, version_id, catalog_id, init='scratch', config=None, base=None, timeout=900):
    r = client.post('/api/ka/jobs/', {'dataset_version_id': version_id, 'catalog_id': catalog_id, 'init': init, 'config': config or {},
                                      'base_model_version_id': base}, format='json')
    assert r.status_code == 201, r.content
    job = r.json()
    assert job['status'] == 'CREATED', job['error']
    assert client.post(f'/api/ka/jobs/{job["id"]}/authorize/', {}, format='json').status_code == 400  # explicit confirmation required
    r = client.post(f'/api/ka/jobs/{job["id"]}/authorize/', {'confirm': True}, format='json')
    assert r.status_code == 200, r.content
    S.run_until_idle(timeout_s=timeout, interval=0.5)
    job = client.get(f'/api/ka/jobs/{job["id"]}/').json()
    assert job['status'] == 'COMPLETED', job['error']
    return job


def _deploy_and_key(client, mv_id, name):
    r = client.post('/api/ka/deployments/', {'model_version_id': mv_id, 'name': name, 'confirm': True}, format='json')
    assert r.status_code == 201, r.content
    dep = r.json()
    key = client.post('/api/ka/api-keys/', {'name': 'test'}, format='json').json()['key']
    return dep, key


def _predict(dep, key, body):
    from django.test import Client

    r = Client().post(dep['endpoint'], body, content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {key}')
    assert r.status_code == 200, r.content
    return r.json()


@pytest.mark.django_db
def test_a_cv_segmentation_on_scanned_drawings(client_a, org_a):
    """Upload scans -> label -> review -> export masks -> train seg -> checkpoint -> eval -> register -> API inference."""
    user, org = org_a
    ds = client_a.post('/api/ka/datasets/', {'name': 'Scans', 'classes': ['wall', 'door', 'window']}, format='json').json()
    from kentucky.models import Dataset, Sheet

    dso = Dataset.objects.get(id=ds['id'])
    plans = {}
    for seed in (41, 42, 43, 44):
        plan = syn.generate_plan(seed)
        buf = io.BytesIO()
        syn.to_raster(plan, 2.0, scanned=True, seed=seed).save(buf, 'PNG')
        res = _upload(client_a, ds['id'], f'scan_{seed}.png', buf.getvalue(), f'bldg-{seed}')
        sheet = Sheet.objects.get(id=res['sheets'][0])
        assert not sheet.has_vector and sheet.vector_provenance == 'raster_inferred'
        F.simulate_cv_annotation(sheet, plan, 'png', user)  # annotator draws polygons in Label Studio
        plans[sheet.id] = plan
    r = client_a.post(f'/api/ka/datasets/{ds["id"]}/sync/', {}, format='json').json()
    assert r['created'] > 50
    ids = [o['id'] for o in client_a.get(f'/api/ka/datasets/{ds["id"]}/objects/?status=pending').json()]
    rev = client_a.post(f'/api/ka/datasets/{ds["id"]}/objects/review/', {'ids': ids, 'status': 'approved'}, format='json').json()
    assert rev['updated'] == len(ids)
    v = client_a.post(f'/api/ka/datasets/{ds["id"]}/versions/', {}, format='json').json()
    assert v['readiness']['ready_for']['semantic_segmentation']
    exp = client_a.post(f'/api/ka/versions/{v["id"]}/export/', {}, format='json').json()
    from django.test import Client

    z = Client().get(exp['url'])
    assert z.status_code == 200 and z.content[:2] == b'PK'
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.startswith('semantic/') for n in names) and 'coco/train.json' in names
    job = _train(client_a, v['id'], 'seg-lraspp-mbv3', config={'epochs': 6, 'crops_per_sheet': 6, 'training_scale': 0.5})
    hist = [h for h in job['metrics_history'] if 'epoch' in h]
    assert hist[-1]['train_loss'] < hist[0]['train_loss']
    assert job['final_metrics']['val']['mean_iou'] is not None
    assert job['resource_usage'].get('checkpoints')  # periodic checkpoints were written
    mv = ModelVersion.objects.get(id=job['model_version'])
    assert mv.license['commercially_deployable'] is True and mv.metrics['headline']['split'] in ('val', 'test')
    dep, key = _deploy_and_key(client_a, mv.id, 'scan-seg')
    sid = next(iter(plans))
    out = _predict(dep, key, {'sheet_id': sid})
    s = Sheet.objects.get(id=sid)
    assert out['image_size'] == [s.width, s.height]
    for p in out['predictions']:
        a = np.array(p['polygon'])
        assert a[:, 0].max() <= s.width + 1 and a[:, 1].max() <= s.height + 1  # drawn over the source sheet
        assert 'polygon_source' in p and p['page'] == 0
    img = base64.b64encode(open(_sheet_png(s), 'rb').read()).decode()
    out2 = _predict(dep, key, {'image': img})
    assert len(out2['predictions']) == len(out['predictions'])
    assert client_a.get('/api/ka/billing/').json()['usage']['by_kind']['inference']['count'] == 2


def _sheet_png(sheet):
    from kentucky import storage

    return storage.path(sheet.image_key)


@pytest.mark.django_db
def test_b_and_c_vector_gnn_and_fine_tuning(client_a, org_a):
    """B: vector PDF/DXF -> primitives -> graph -> Graph Studio edits via API -> validate -> PyG -> GAT -> inference.
    C: fine-tune from the registered checkpoint, compare with baseline, new version, deploy + rollback."""
    user, org = org_a
    ds = client_a.post('/api/ka/datasets/', {'name': 'Vector plans'}, format='json').json()
    from kentucky.models import Sheet

    sheets = []
    for seed, fmt, rot in [(51, 'pdf', 0), (52, 'pdf', 90), (53, 'dxf', 0), (54, 'pdf', 0), (55, 'pdf', 270), (56, 'dxf', 0)]:
        plan = syn.generate_plan(seed)
        data = syn.to_pdf(plan, rot) if fmt == 'pdf' else syn.to_dxf(plan)
        res = _upload(client_a, ds['id'], f'plan_{seed}.{fmt}', data, f'bldg-{seed}')
        s = Sheet.objects.get(id=res['sheets'][0])
        assert s.has_vector
        prims = client_a.get(f'/api/ka/sheets/{s.id}/primitives/').json()['primitives']
        assert len(prims) >= len([p for p in plan.prims if p.kind != 'text'])
        g = client_a.get(f'/api/ka/sheets/{s.id}/graph/').json()
        assert g['version'] == 1 and g['stats']['edges'] > 100
        # Graph Studio edit: label nodes, correct edges, group objects (computed by the simulated annotator) and save via API
        F.simulate_graph_labeling(s, plan, fmt, user, approve=False)
        labeled = SheetGraph.objects.get(sheet=s, is_current=True).graph
        # an annotator removes a wrong candidate edge and adds a relation by hand
        removed = labeled['edges'].pop()
        r = client_a.post(f'/api/ka/sheets/{s.id}/graph/', {'graph': labeled, 'base_version': 1, 'message': 'stale'}, format='json')
        assert r.status_code == 409  # optimistic concurrency: v2 already exists
        r = client_a.post(f'/api/ka/sheets/{s.id}/graph/', {'graph': labeled, 'base_version': 2, 'message': 'labeled'}, format='json')
        assert r.status_code == 201, r.content
        assert not any(e['id'] == removed['id'] for e in SheetGraph.objects.get(sheet=s, is_current=True).graph['edges'])
        bad = {**labeled, 'edges': labeled['edges'] + [{'id': 'x', 'source': 'nope', 'target': labeled['nodes'][0]['id'], 'type': 'near', 'label': 'none', 'features': [0] * 9}]}
        assert client_a.post(f'/api/ka/sheets/{s.id}/graph/', {'graph': bad, 'base_version': 3}, format='json').status_code == 400
        assert client_a.post(f'/api/ka/sheets/{s.id}/graph/review/', {'status': 'approved'}, format='json').status_code == 200
        sheets.append((s, plan, fmt))
    v = client_a.post(f'/api/ka/datasets/{ds["id"]}/versions/', {}, format='json').json()
    assert v['readiness']['ready_for']['node_classification'] and v['graphs'] == 6
    job = _train(client_a, v['id'], 'gnn-gat-node', config={'epochs': 120})
    split = job['final_metrics'].get('test') if job['final_metrics'].get('test', {}).get('n') else job['final_metrics']['val']
    assert split['macro_f1'] > 0.5 and split['accuracy'] > 0.7  # real learning on held-out buildings (5 classes)
    mv1 = job['model_version']
    dep, key = _deploy_and_key(client_a, mv1, 'node-cls')
    s, plan, fmt = sheets[0]
    out = _predict(dep, key, {'sheet_id': s.id})
    assert 'nodes' in out, {k: (v if k != 'predictions' else len(v)) for k, v in out.items()}
    assert len(out['nodes']) == SheetGraph.objects.filter(sheet=s).order_by('version').first().stats['nodes']
    g = client_a.get(f'/api/ka/sheets/{s.id}/graph/').json()['graph']
    out2 = _predict(dep, key, {'graph': g})
    gt = {n['id']: n['label'] for n in g['nodes']}
    acc = np.mean([gt[n['id']] == n['label'] for n in out2['nodes']])
    assert acc > 0.6 and all(n['primitive_ids'] for n in out2['nodes'])
    # ---- Test C: fine-tune from the registered checkpoint on a new dataset version
    v2 = client_a.post(f'/api/ka/datasets/{ds["id"]}/versions/', {'seed': 1}, format='json').json()
    job2 = _train(client_a, v2['id'], 'gnn-gat-node', init='checkpoint', base=mv1, config={'epochs': 40})
    mv2 = ModelVersion.objects.get(id=job2['model_version'])
    assert mv2.model_id == ModelVersion.objects.get(id=mv1).model_id and mv2.version == 2
    assert mv2.license['base_model_version'] == mv1
    assert any('Loaded' in (h.get('log') or '') for h in job2['metrics_history'])
    cmp = client_a.get(f'/api/ka/jobs/compare/?ids={job["id"]},{job2["id"]}').json()
    assert len(cmp['rows']) == 2 and 'epochs' in cmp['config_differences']
    r = client_a.post(f'/api/ka/deployments/{dep["id"]}/set-version/', {'model_version_id': mv2.id}, format='json').json()
    assert r['active_version'] == mv2.id
    assert _predict(dep, key, {'sheet_id': s.id})['model_version'] == mv2.id
    r = client_a.post(f'/api/ka/deployments/{dep["id"]}/rollback/', {}, format='json').json()
    assert r['active_version'] == mv1


@pytest.mark.django_db
def test_d_agentic_annotation_with_provenance(client_a, org_a):
    """Agent proposes -> human accepts / edits / rejects -> provenance kept -> only approved data is exported."""
    user, org = org_a
    ds = client_a.post('/api/ka/datasets/', {'name': 'Agent'}, format='json').json()
    plan = syn.generate_plan(61)
    res = _upload(client_a, ds['id'], 'plan_61.pdf', syn.to_pdf(plan), 'b61')
    sid = res['sheets'][0]
    sug = client_a.post(f'/api/ka/datasets/{ds["id"]}/agent/suggest-classes/', {}, format='json').json()
    assert sug['created'] >= 1
    r = client_a.post(f'/api/ka/datasets/{ds["id"]}/agent/propose-graph/', {'sheet_id': sid}, format='json').json()
    assert r['created'] > 10
    r = client_a.post(f'/api/ka/datasets/{ds["id"]}/agent/propose-cv/', {'sheet_id': sid}, format='json').json()
    assert r['created'] > 5
    props = client_a.get(f'/api/ka/datasets/{ds["id"]}/proposals/?kind=cv_object&status=pending').json()
    assert all(p['agent'] == 'ka-geometry-agent' and p['evidence'].get('rule') and p['confidence'] is not None for p in props)
    assert Proposal.objects.filter(id__in=[p['id'] for p in props]).exclude(ls_prediction_id=None).count() == len(props)  # visible in LS editor
    acc, mod, rej = props[0], props[1], props[2]
    assert client_a.post(f'/api/ka/proposals/{acc["id"]}/review/', {'action': 'accept'}, format='json').status_code == 200
    edited = {**mod['payload'], 'polygon': [[x + 1, y] for x, y in mod['payload']['polygon']]}
    assert client_a.post(f'/api/ka/proposals/{mod["id"]}/review/', {'action': 'modify', 'final_payload': edited}, format='json').json()['status'] == 'modified'
    assert client_a.post(f'/api/ka/proposals/{rej["id"]}/review/', {'action': 'reject'}, format='json').status_code == 200
    # original proposal payload is never mutated
    assert Proposal.objects.get(id=mod['id']).payload == mod['payload']
    objs = CanonicalObject.objects.filter(dataset_id=ds['id'])
    assert objs.count() == 2 and set(objs.values_list('provenance', flat=True)) == {'agent_accepted'}
    assert set(objs.values_list('review_status', flat=True)) == {'pending'}  # accepted != verified: still needs review
    # graph proposals: accept high-confidence, the rest stay pending
    r = client_a.post(f'/api/ka/sheets/{sid}/proposals/apply/', {'min_confidence': 0.8, 'accept': True}, format='json').json()
    g = SheetGraph.objects.get(sheet_id=sid, is_current=True)
    accepted_nodes = [n for n in g.graph['nodes'] if n.get('provenance') == 'agent_accepted']
    assert r['applied'] > 0 and accepted_nodes and all(n.get('proposal_id') for n in accepted_nodes)
    # human reviews one object (approve) and leaves the edited one pending
    o_ok = objs.get(proposal_id=acc['id'])
    client_a.post(f'/api/ka/datasets/{ds["id"]}/objects/review/', {'ids': [o_ok.id], 'status': 'approved'}, format='json')
    v = client_a.post(f'/api/ka/datasets/{ds["id"]}/versions/', {}, format='json').json()
    from kentucky.models import DatasetVersion

    man = DatasetVersion.objects.get(id=v['id']).manifest
    assert [o['uid'] for o in man['objects']] == [o_ok.uid] and man['objects'][0]['proposal_id'] == acc['id']
    rejected_poly = rej['payload']['polygon']
    assert not any(o['geometry'].get('polygon') == rejected_poly for o in man['objects'])
    # QA agent
    r = client_a.post(f'/api/ka/datasets/{ds["id"]}/agent/quality-review/', {}, format='json').json()
    flags = client_a.get(f'/api/ka/datasets/{ds["id"]}/proposals/?kind=quality_flag').json()
    assert r['created'] == len(flags) and any(f['payload']['issue'] == 'possible_missing_object' for f in flags)
    summary = client_a.post(f'/api/ka/datasets/{ds["id"]}/agent/summary/', {}, format='json').json()
    assert summary['recommendations'] and 'rule-based' in summary['generated_by']


@pytest.mark.django_db
def test_ls_prediction_acceptance_records_agent_provenance(org_a):
    """An annotation created in the LS editor from an agent prediction syncs as agent_accepted (not human)."""
    from tasks.models import Annotation, Prediction

    from kentucky.agent.labeling_assistant import propose_cv_from_graph
    from kentucky.labeling import sync_from_label_studio

    user, org = org_a
    ds = F.make_dataset(org, user)
    plan, doc, sheet = F.upload_plan(ds, user, 71, 'pdf')
    propose_cv_from_graph(sheet, ds)
    p = Proposal.objects.filter(sheet=sheet, kind='cv_object').first()
    pred = Prediction.objects.get(id=p.ls_prediction_id)
    Annotation.objects.create(task_id=sheet.ls_task_id, project_id=pred.project_id, result=pred.result, completed_by=user, parent_prediction=pred)
    sync_from_label_studio(ds)
    o = CanonicalObject.objects.get(sheet=sheet)
    assert o.provenance == 'agent_accepted' and o.proposal_id == p.id and o.review_status == 'pending'
