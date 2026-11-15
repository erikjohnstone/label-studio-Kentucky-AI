"""GNN training track (PyTorch Geometric): node classification + edge/relation classification.

Trains on the real candidate graph structure (edge_index + edge features) exported per sheet.
Unverified labels are -1 and ignored by the loss. Django-free.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.loader import DataLoader
from torch_geometric.nn import GATv2Conv, GCNConv, GINEConv, GPSConv, SAGEConv

from . import metrics as M
from .cv import _maybe_fault, make_optimizer, make_scheduler
from .events import check_cancel


class NodeGNN(nn.Module):
    def __init__(self, kind, in_dim, edge_dim, hidden, out_dim, layers=3, heads=4, dropout=0.2):
        super().__init__()
        self.kind = kind
        self.inp = nn.Linear(in_dim, hidden)
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()
        for _ in range(layers):
            if kind == 'gps':
                # graph transformer: local GINE message passing (uses touch / cross / parallel edge geometry)
                # + global attention across the whole sheet, so a line can "see" distant context (room, wall run)
                mlp = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, hidden))
                self.convs.append(GPSConv(hidden, GINEConv(mlp, edge_dim=edge_dim), heads=heads, dropout=dropout,
                                          norm='layer_norm', attn_type='multihead'))
            elif kind == 'gat':
                self.convs.append(GATv2Conv(hidden, hidden // heads, heads=heads, edge_dim=edge_dim))
            elif kind == 'gcn':
                self.convs.append(GCNConv(hidden, hidden))
            else:
                self.convs.append(SAGEConv(hidden, hidden))
            self.norms.append(nn.LayerNorm(hidden))
        self.dropout = dropout
        self.head = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, out_dim))

    def encode(self, x, edge_index, edge_attr=None, batch=None):
        h = F.relu(self.inp(x))
        for conv, norm in zip(self.convs, self.norms):
            if self.kind == 'gps':
                h = conv(h, edge_index, batch, edge_attr=edge_attr)  # GPS layers carry their own residuals + norms
                continue
            hn = conv(h, edge_index, edge_attr) if self.kind == 'gat' else conv(h, edge_index)
            h = norm(h + F.dropout(F.relu(hn), self.dropout, self.training))
        return h

    def forward(self, data):
        return self.head(self.encode(data.x, data.edge_index, data.edge_attr, getattr(data, 'batch', None)))


class EdgeGNN(nn.Module):
    def __init__(self, in_dim, edge_dim, hidden, out_dim, layers=3, dropout=0.2, **_):
        super().__init__()
        self.enc = NodeGNN('sage', in_dim, edge_dim, hidden, hidden, layers, dropout=dropout)
        self.edge_mlp = nn.Sequential(nn.Linear(3 * hidden + edge_dim, hidden), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden, out_dim))

    def forward(self, data):
        h = self.enc.encode(data.x, data.edge_index, data.edge_attr)
        s, d = data.edge_index
        return self.edge_mlp(torch.cat([h[s], h[d], (h[s] - h[d]).abs(), data.edge_attr], dim=1))


KIND = {'gnn-sage-node': 'sage', 'gnn-gat-node': 'gat', 'gnn-gcn-node': 'gcn', 'gnn-gps-node': 'gps'}


def build(catalog_id, meta, n_out, cfg):
    if catalog_id == 'gnn-sage-edge':
        return EdgeGNN(meta['node_dim'], meta['edge_dim'], cfg['hidden'], n_out, cfg['layers'], cfg['dropout'])
    return NodeGNN(KIND[catalog_id], meta['node_dim'], meta['edge_dim'], cfg['hidden'], n_out, cfg['layers'],
                   cfg.get('heads', 4), cfg['dropout'])


def _targets(data, task):
    return data.y if task == 'node_classification' else data.edge_y


def _weights(items, task, n, mode):
    ys = torch.cat([_targets(d, task) for d in items]) if items else torch.zeros(0, dtype=torch.long)
    ys = ys[ys >= 0]
    counts = np.bincount(ys.numpy(), minlength=n).astype(float)
    if mode == 'none':
        return None, counts
    from .cv import class_weights

    return class_weights(counts, mode), counts


@torch.no_grad()
def predict(model, data):
    model.eval()
    logits = model(data)
    prob = torch.softmax(logits, -1)
    conf, cls = prob.max(-1)
    return cls, conf, prob


def evaluate(model, items, task, classes):
    yt, yp = [], []
    consistency = {'same_object_components': 0, 'mixed_label_components': 0}
    for d in items:
        cls, _, _ = predict(model, d)
        t = _targets(d, task)
        m = t >= 0
        yt.append(t[m].numpy())
        yp.append(cls[m].numpy())
        if task == 'edge_classification' and 'same_object' in classes:
            consistency_update(consistency, d, cls, classes)
    if not yt:
        return {'n': 0}
    rep = M.classification_report(np.concatenate(yt), np.concatenate(yp), classes)
    if task == 'edge_classification':
        rep['graph_consistency'] = consistency
    return rep


def consistency_update(acc, d, cls, classes):
    """Graph topology check: components formed by predicted same_object edges whose member nodes carry
    different ground-truth node labels are topology errors (objects merged across classes)."""
    so = classes.index('same_object')
    n = d.x.shape[0]
    parent = list(range(n))

    def f(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    ei = d.edge_index
    for k in torch.nonzero(cls == so).flatten().tolist():
        a, b = f(int(ei[0, k])), f(int(ei[1, k]))
        if a != b:
            parent[a] = b
    comps = {}
    for i in range(n):
        comps.setdefault(f(i), []).append(i)
    for members in comps.values():
        if len(members) < 2:
            continue
        acc['same_object_components'] += 1
        labs = {int(d.y[i]) for i in members if int(d.y[i]) >= 0}
        if len(labs) > 1:
            acc['mixed_label_components'] += 1


def train_gnn(spec, reporter, deadline):
    bundle, out = Path(spec['bundle_dir']), Path(spec['out_dir'])
    cfg, cid, task = spec['config'], spec['catalog_id'], spec['task']
    meta = json.loads((bundle / 'pyg' / 'meta.json').read_text())
    classes = meta['node_classes'] if task == 'node_classification' else meta['edge_classes']
    random.seed(cfg['seed'])
    torch.manual_seed(cfg['seed'])
    np.random.seed(cfg['seed'])
    load = lambda s: torch.load(bundle / 'pyg' / f'{s}.pt', weights_only=False) if (bundle / 'pyg' / f'{s}.pt').exists() else []
    train, val, test = load('train'), load('val'), load('test')
    train = [d for d in train if (_targets(d, task) >= 0).any()]
    if not train:
        raise ValueError('No verified labels in the training split for this task')
    if not val:
        reporter.log('Validation split empty: validating on training graphs (optimistic)')
        val = train
    weights, counts = _weights(train, task, len(classes), cfg.get('class_weighting', 'sqrt_inverse'))
    model = build(cid, meta, len(classes), cfg)
    if spec.get('base_checkpoint'):
        ck = torch.load(spec['base_checkpoint'], map_location='cpu', weights_only=False)
        own = model.state_dict()
        ok = {k: v for k, v in ck['state_dict'].items() if k in own and own[k].shape == v.shape}
        own.update(ok)
        model.load_state_dict(own)
        reporter.log(f'Loaded {len(ok)}/{len(own)} tensors from base checkpoint')
    opt = make_optimizer(model.parameters(), cfg)
    sched = make_scheduler(opt, cfg)
    loader = DataLoader(train, batch_size=cfg['batch_size'], shuffle=True)
    reporter.status('TRAINING', classes=classes, train_graphs=len(train), val_graphs=len(val), label_counts=counts.tolist())
    best, best_epoch, bad = -1.0, -1, 0
    if spec.get('base_checkpoint'):  # continuing: the result can never be worse than where it started
        best, best_epoch = evaluate(model, val, task, classes).get('macro_f1') or 0.0, 0
        save(out / 'best.pt', model, spec, classes, meta, 0)
        reporter.log(f'Starting model scores {best:.3f} macro-F1 on the check graphs; kept unless training beats it')
    for epoch in range(cfg['epochs']):
        check_cancel(spec['job_dir'])
        if time.time() > deadline:
            raise TimeoutError('max runtime exceeded')
        model.train()
        losses = []
        for batch in loader:
            logits = model(batch)
            t = _targets(batch, task)
            loss = F.cross_entropy(logits, t, weight=weights, ignore_index=-1)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss))
        rec = {'epoch': epoch + 1, 'train_loss': float(np.mean(losses)), 'lr': opt.param_groups[0]['lr']}
        if (epoch + 1) % cfg['val_every'] == 0 or epoch + 1 == cfg['epochs']:
            model.eval()
            with torch.no_grad():
                vl = [float(F.cross_entropy(model(d), _targets(d, task), weight=weights, ignore_index=-1))
                      for d in val if (_targets(d, task) >= 0).any()]
            rep = evaluate(model, val, task, classes)
            rec.update({'val_loss': float(np.mean(vl)) if vl else None, 'val_macro_f1': rep.get('macro_f1'),
                        'val_accuracy': rep.get('accuracy')})
            score = rep.get('macro_f1') or 0.0
            if score > best:
                best, best_epoch, bad = score, epoch + 1, 0
                save(out / 'best.pt', model, spec, classes, meta, epoch + 1)
            else:
                bad += 1
            if sched is not None and cfg['scheduler'] == 'plateau' and rec['val_loss'] is not None:
                sched.step(rec['val_loss'])
        if sched is not None and cfg['scheduler'] != 'plateau':
            sched.step()
        if (epoch + 1) % 10 == 0 or epoch == 0:
            reporter.metric(**rec)
            reporter.heartbeat()
        if (epoch + 1) % cfg['checkpoint_every'] == 0 and (epoch + 1) % 25 == 0:
            save(out / f'epoch_{epoch + 1}.pt', model, spec, classes, meta, epoch + 1)
            reporter.emit('checkpoint', path=f'epoch_{epoch + 1}.pt', epoch=epoch + 1)
        _maybe_fault(spec, epoch)
        if bad >= cfg['early_stopping_patience'] * 4:
            reporter.metric(**rec)
            reporter.log(f'Early stopping at epoch {epoch + 1} (best {best_epoch})')
            break
    reporter.status('EVALUATING')
    ck = torch.load(out / 'best.pt', map_location='cpu', weights_only=False)
    model.load_state_dict(ck['state_dict'])
    final = {'best_epoch': best_epoch, 'kept_starting_model': best_epoch == 0, 'task': task, 'classes': classes, 'val': evaluate(model, val, task, classes)}
    if test:
        final['test'] = evaluate(model, test, task, classes)
    hl = final.get('test') if test and final['test'].get('n') else final['val']
    final['headline'] = {'macro_f1': hl.get('macro_f1'), 'accuracy': hl.get('accuracy'), 'split': 'test' if test and final['test'].get('n') else 'val'}
    return final, out / 'best.pt'


def save(path, model, spec, classes, meta, epoch):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({'format': 'ka-checkpoint-1', 'catalog_id': spec['catalog_id'], 'task': spec['task'], 'init': spec['init'],
                'config': spec['config'], 'classes': classes, 'epoch': epoch, 'state_dict': model.state_dict(),
                'graph_meta': meta, 'preprocess': {'feature_spec': meta['feature_spec']['version']}}, path)


def load_model(ck):
    cfg = ck['config']
    m = build(ck['catalog_id'], ck['graph_meta'], len(ck['classes']), cfg)
    m.load_state_dict(ck['state_dict'])
    m.eval()
    return m
