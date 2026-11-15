"""Training Center advanced mode: defaults + schema, per-architecture estimates, explicit architecture /
starting point / validated settings on one-click training, and the Experiments data the UI relies on."""

import pytest


@pytest.mark.django_db
def test_advanced_training_options(client_a, labeled_dataset):
    ds, _ = labeled_dataset
    r = client_a.get('/api/ka/training/defaults/?catalog_id=gnn-sage-node&train_items=3')
    assert r.status_code == 200 and r.data['config']['epochs'] > 0 and r.data['schema']['epochs']['min'] == 1
    assert client_a.get('/api/ka/training/defaults/?catalog_id=nope').status_code == 400

    est = client_a.get(f'/api/ka/datasets/{ds.id}/estimate/?catalog_id=inst-maskrcnn-mbv3&epochs=3').data
    est_long = client_a.get(f'/api/ka/datasets/{ds.id}/estimate/?catalog_id=inst-maskrcnn-mbv3&epochs=30').data
    assert est_long['cpu-local']['seconds_high'] > est['cpu-local']['seconds_high']
    assert client_a.get(f'/api/ka/datasets/{ds.id}/estimate/?catalog_id=inst-maskrcnn-mbv3&epochs=0').status_code == 400

    # explicit architecture + start from zero + custom settings (stored exactly for reproducibility)
    r = client_a.post(f'/api/ka/datasets/{ds.id}/train/', {'catalog_id': 'gnn-sage-node', 'init': 'scratch', 'config': {'epochs': 3, 'seed': 7}}, format='json')
    assert r.status_code == 201 and r.data['ready']
    j = r.data['job']
    assert j['catalog_id'] == 'gnn-sage-node' and j['init'] == 'scratch' and j['config']['epochs'] == 3 and j['seed'] == 7
    assert j['task'] == 'node_classification' and j['architecture'].startswith('GraphSAGE')

    # an unsupported setting never reaches a worker
    r = client_a.post(f'/api/ka/datasets/{ds.id}/train/', {'catalog_id': 'gnn-sage-node', 'init': 'scratch', 'config': {'epochs': 0}}, format='json')
    assert r.status_code == 400 or r.data['job']['status'] == 'FAILED'
    assert client_a.post(f'/api/ka/datasets/{ds.id}/train/', {'catalog_id': 'nope'}, format='json').status_code == 400

    # Experiments list carries lineage for every run
    runs = client_a.get('/api/ka/jobs/').data
    assert runs and {'architecture', 'dataset_name', 'base_version', 'deployed'} <= set(runs[0])
