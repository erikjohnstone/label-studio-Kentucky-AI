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


NICE = {'wall': 'walls', 'door': 'doors', 'window': 'windows', 'room': 'rooms', 'room_tag': 'room names', 'floor_finish': 'flooring areas',
        'ceiling': 'ceilings', 'roof': 'roof areas', 'duct': 'duct runs', 'diffuser': 'diffusers', 'hvac_equipment': 'HVAC units',
        'electrical_device': 'electrical devices', 'plumbing_fixture': 'plumbing fixtures', 'structural_member': 'structural members',
        'same_object': 'pieces that belong together', 'hosted_by': 'doors/windows sitting in a wall', 'none': 'unrelated lines',
        'other': 'other linework', 'connects_to': 'connections', 'labels': 'labels', 'bounded_by': 'room boundaries', 'contained_in': 'parts'}


def report_card(final_metrics: dict, task: str) -> dict | None:
    """Plain-language accuracy summary for contractors, derived only from measured test/validation metrics."""
    if not final_metrics:
        return None
    for split_name in ('test', 'val'):
        rc = _report_card(final_metrics, task, split_name)
        if rc:
            return rc
    return None


def _report_card(final_metrics: dict, task: str, split_name: str) -> dict | None:
    sp = final_metrics.get(split_name) or {}
    items = []
    if task == 'semantic_segmentation':
        objs = sp.get('objects') or {}
        for c, v in (sp.get('per_class') or {}).items():
            if c == '__background__' or not v.get('gt_pixels'):
                continue
            found = (1 - objs[c]['missing_rate']) if c in objs else (v.get('recall') or 0)
            tot = objs[c]['gt_count'] if c in objs else None
            items.append({'key': c, 'score': found, 'outline': v.get('iou'), 'total': tot, 'found': round(found * tot) if tot else None})
    elif task == 'instance_segmentation':
        for c, v in (sp.get('per_class_pr') or {}).items():
            tot = (v.get('tp') or 0) + (v.get('fn') or 0)
            items.append({'key': c, 'score': v.get('recall') or 0, 'outline': (sp.get('per_class_ap') or {}).get(c), 'total': tot, 'found': v.get('tp')})
    else:
        for c, v in (sp.get('per_class') or {}).items():
            if v.get('support'):
                items.append({'key': c, 'score': v.get('recall') or 0, 'outline': v.get('f1'), 'total': v['support'], 'found': round((v.get('recall') or 0) * v['support'])})
    if not items:
        return None
    for i in items:
        n = round(i['score'] * 10)
        i['name'] = NICE.get(i['key'], i['key'].replace('_', ' '))
        i['sentence'] = f'Finds about {n} out of 10 {i["name"]}'
        i['level'] = 'great' if i['score'] >= 0.9 else 'good' if i['score'] >= 0.75 else 'fair' if i['score'] >= 0.5 else 'weak'
    mean = sum(i['score'] for i in items) / len(items)
    grade = 'A' if mean >= 0.9 else 'B' if mean >= 0.8 else 'C' if mean >= 0.65 else 'D' if mean >= 0.5 else 'Not ready'
    weak = [i['name'] for i in sorted(items, key=lambda x: x['score']) if i['level'] in ('weak', 'fair')]
    advice = (f'Label more {" and ".join(weak[:2])} on a few more plans, then train again.' if weak
              else 'Looks solid. Try it on a plan it has never seen before turning it on.')
    weakest = min(items, key=lambda x: x['score'])
    sentence = ('Ready to use.' if mean >= 0.75 else 'Not ready yet.') + (f' Misses some {weakest["name"]} now and then.' if weakest['score'] < 0.95 else ' Finds nearly everything it was tested on.')
    return {'grade': grade, 'score': round(mean, 3), 'sentence': sentence, 'items': sorted(items, key=lambda x: -x['score']), 'advice': advice,
            'checked_on': 'plans it never saw while learning' if split_name == 'test' else 'a held-back check set',
            'ready_to_use': mean >= 0.75}
