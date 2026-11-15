"""Training Center assistant (rule-based analysis of real dataset statistics and real training metrics).

Outputs are computed from the data; nothing is generated text pretending to be measurements.
"""

from __future__ import annotations

import numpy as np

from .. import catalog

ADVISOR = 'ka-training-advisor@1.0.0 (rule-based)'


def recommend(version, registered_versions=()) -> dict:
    rd = version.readiness or {}
    st = rd.get('stats', {})
    ready = rd.get('ready_for', {})
    n_train = len(version.splits.get('train', []))
    out = {'advisor': ADVISOR, 'tasks': [], 'warnings': []}
    for task, ok in ready.items():
        if not ok:
            continue
        options = [c for c in catalog.CATALOG if c['task'] == task]
        own = [mv for mv in registered_versions if mv.model.task == task]
        best = None
        if own:
            best = max(own, key=lambda mv: (mv.metrics.get('headline') or {}).get('macro_f1') or
                       (mv.metrics.get('headline') or {}).get('mean_iou') or 0)
        if task.startswith('node') or task.startswith('edge'):
            pick = 'gnn-gat-node' if task == 'node_classification' else 'gnn-sage-edge'
            why = 'Edge-aware attention uses candidate-edge geometry (touch / cross / parallel), which carries most of the signal on drawings.' \
                if task == 'node_classification' else 'Only relation-classification template.'
        elif task == 'semantic_segmentation':
            pick = 'seg-lraspp-mbv3'
            why = 'Fast, CPU-trainable baseline; try SegFormer once you have > 50 labeled sheets.'
        else:
            pick = 'inst-maskrcnn-mbv3'
            why = 'CPU-trainable Mask R-CNN; move to ResNet-50 v2 on GPU for production accuracy.'
        init = 'checkpoint' if best else 'scratch'
        init_why = (f'Fine-tune your model {best.model.name} v{best.version} (same architecture) - usually beats scratch on small data.'
                    if best else 'No compatible fine-tunable checkpoint you own; open checkpoints that are not cleared for commercial use '
                                 'would block deployment, so train from scratch.')
        if best and best.model.catalog_id != pick:
            pick = best.model.catalog_id
        out['tasks'].append({'task': task, 'catalog_id': pick, 'why': why, 'init': init, 'init_why': init_why,
                             'base_model_version': best.id if best else None,
                             'options': [o['id'] for o in options]})
    if n_train < 5:
        out['warnings'].append(f'Only {n_train} training sheets: expect high variance; metrics on val/test are indicative only.')
    cc = st.get('class_counts', {})
    if cc:
        hi, lo = max(cc.values()), max(min(cc.values()), 1)
        if hi / lo > 10:
            out['warnings'].append(f'Class imbalance {hi}:{lo}; class-weighted loss is enabled by default; add examples of rare classes.')
    nc = st.get('node_label_counts', {})
    if nc and max(nc.values()) / max(min(nc.values()), 1) > 10:
        out['warnings'].append('Node label imbalance > 10:1 (walls dominate on most plans); macro-F1 is the headline metric.')
    aug = ['flip', 'rot90']
    if st.get('raster_sheets'):
        aug += ['brightness', 'noise']
    out['augmentations'] = {'recommended': aug, 'why': 'Drawings are orientation-invariant; scans add brightness/noise variation.'}
    return out


def diagnose(job) -> dict:
    hist = [h for h in job.metrics_history if 'epoch' in h and h.get('train_loss') is not None]
    out = {'advisor': ADVISOR, 'job': job.id, 'findings': []}
    vals = [(h['epoch'], h['val_loss']) for h in hist if h.get('val_loss') is not None]
    if len(vals) >= 4:
        ep, vl = zip(*vals)
        best_i = int(np.argmin(vl))
        tl = [h['train_loss'] for h in hist]
        if best_i < len(vl) - 3 and vl[-1] > vl[best_i] * 1.15 and tl[-1] < tl[0]:
            out['findings'].append({'code': 'overfitting', 'message': f'Validation loss bottomed at epoch {ep[best_i]} ({vl[best_i]:.3f}) and rose to '
                                    f'{vl[-1]:.3f} while training loss kept falling. The best checkpoint (epoch {ep[best_i]}) was kept. '
                                    'Add data/augmentation or reduce epochs.'})
        if tl[-1] > 0.9 * tl[0]:
            out['findings'].append({'code': 'underfitting', 'message': 'Training loss barely decreased: raise learning rate / epochs, or check labels.'})
    fm = job.final_metrics or {}
    split = fm.get('test') or fm.get('val') or {}
    per = split.get('per_class') or {}
    weak = []
    for c, v in per.items():
        score = v.get('f1') if 'f1' in v else v.get('iou')
        if c != '__background__' and score is not None and (v.get('support', 1) or v.get('gt_pixels', 1)):
            weak.append((score, c))
    weak.sort()
    if weak:
        out['findings'].append({'code': 'weakest_classes', 'message': 'Weakest classes: ' + ', '.join(f'{c} ({s:.2f})' for s, c in weak[:3]),
                                'suggestion': 'Label more examples of these classes, especially from buildings not yet in the dataset.'})
    if 'by_drawing_type' in split:
        out['findings'].append({'code': 'vector_vs_scan', 'message': f'mIoU by drawing type: {split["by_drawing_type"]}'})
    if fm.get('val') and fm.get('test'):
        a = (fm['val'].get('macro_f1') or fm['val'].get('mean_iou') or 0)
        b = (fm['test'].get('macro_f1') or fm['test'].get('mean_iou') or 0)
        if a - b > 0.15:
            out['findings'].append({'code': 'generalization_gap', 'message': f'Val {a:.2f} vs test {b:.2f}: the held-out building differs; '
                                    'more building diversity is needed.'})
    return out


def compare(jobs) -> dict:
    rows = []
    keys = set()
    for j in jobs:
        keys |= set(j.config)
    for j in jobs:
        h = (j.final_metrics or {}).get('headline', {})
        rows.append({'job': j.id, 'name': j.name, 'catalog_id': j.catalog_id, 'init': j.init, 'status': j.status,
                     'dataset_version': j.dataset_version.version, 'headline': h,
                     'runtime_s': (j.resource_usage or {}).get('runtime_s')})
    diffs = {k: [j.config.get(k) for j in jobs] for k in sorted(keys) if len({str(j.config.get(k)) for j in jobs}) > 1}
    return {'advisor': ADVISOR, 'rows': rows, 'config_differences': diffs}
