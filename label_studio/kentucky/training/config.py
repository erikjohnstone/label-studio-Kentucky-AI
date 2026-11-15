"""Recommended defaults and validation for every approved training template. Django-free."""

from __future__ import annotations

import copy
import os

COMMON = {'seed': 0, 'early_stopping_patience': 8, 'checkpoint_every': 5, 'val_every': 1, 'max_runtime_s': 3600}

DEFAULTS = {
    'seg-lraspp-mbv3': {'epochs': 30, 'batch_size': 4, 'lr': 1e-3, 'optimizer': 'adamw', 'weight_decay': 1e-4, 'scheduler': 'cosine',
                        'training_scale': 0.5, 'crop_size': 320, 'crops_per_sheet': 8, 'augment': ['flip', 'rot90', 'brightness', 'noise'],
                        'class_weighting': 'sqrt_inverse'},
    'seg-dinov2-s': {'epochs': 30, 'early_stopping_patience': 15, 'batch_size': 4, 'lr': 1e-3, 'optimizer': 'adamw', 'weight_decay': 1e-2, 'scheduler': 'cosine',
                     'training_scale': 0.5, 'crop_size': 322, 'crops_per_sheet': 6, 'augment': ['flip', 'rot90', 'brightness', 'noise'],
                     'class_weighting': 'sqrt_inverse'},
    'seg-segformer-b0': {'epochs': 30, 'batch_size': 4, 'lr': 6e-4, 'optimizer': 'adamw', 'weight_decay': 1e-2, 'scheduler': 'cosine',
                         'training_scale': 0.5, 'crop_size': 256, 'crops_per_sheet': 8, 'augment': ['flip', 'rot90', 'brightness', 'noise'],
                         'class_weighting': 'sqrt_inverse'},
    'inst-maskrcnn-mbv3': {'epochs': 20, 'batch_size': 2, 'lr': 1e-3, 'optimizer': 'adamw', 'weight_decay': 1e-4, 'scheduler': 'cosine',
                           'training_scale': 0.5, 'crop_size': 384, 'crops_per_sheet': 6, 'augment': ['flip'], 'score_threshold': 0.5},
    'det-rtdetrv2-r18': {'epochs': 30, 'batch_size': 4, 'lr': 1e-4, 'optimizer': 'adamw', 'weight_decay': 1e-4, 'scheduler': 'cosine',
                         'training_scale': 0.5, 'crop_size': 640, 'crops_per_sheet': 4, 'augment': ['flip'], 'score_threshold': 0.4},
    'det-dfine-s': {'epochs': 30, 'batch_size': 4, 'lr': 1e-4, 'optimizer': 'adamw', 'weight_decay': 1e-4, 'scheduler': 'cosine',
                    'training_scale': 0.5, 'crop_size': 640, 'crops_per_sheet': 4, 'augment': ['flip'], 'score_threshold': 0.4},
    'inst-maskrcnn-r50-v2': {'epochs': 24, 'batch_size': 2, 'lr': 1e-2, 'optimizer': 'sgd', 'weight_decay': 1e-4, 'scheduler': 'step',
                             'training_scale': 0.75, 'crop_size': 800, 'crops_per_sheet': 4, 'augment': ['flip'], 'score_threshold': 0.5},
    'gnn-sage-node': {'epochs': 150, 'batch_size': 4, 'lr': 5e-3, 'optimizer': 'adamw', 'weight_decay': 5e-4, 'scheduler': 'plateau',
                      'hidden': 96, 'layers': 3, 'dropout': 0.2, 'class_weighting': 'sqrt_inverse'},
    'gnn-gat-node': {'epochs': 150, 'batch_size': 4, 'lr': 3e-3, 'optimizer': 'adamw', 'weight_decay': 5e-4, 'scheduler': 'plateau',
                     'hidden': 64, 'layers': 3, 'heads': 4, 'dropout': 0.2, 'class_weighting': 'sqrt_inverse'},
    'gnn-gps-node': {'epochs': 150, 'batch_size': 4, 'lr': 1e-3, 'optimizer': 'adamw', 'weight_decay': 1e-4, 'scheduler': 'plateau',
                     'hidden': 64, 'layers': 3, 'heads': 4, 'dropout': 0.1, 'class_weighting': 'sqrt_inverse'},
    'gnn-gcn-node': {'epochs': 150, 'batch_size': 4, 'lr': 5e-3, 'optimizer': 'adamw', 'weight_decay': 5e-4, 'scheduler': 'plateau',
                     'hidden': 96, 'layers': 3, 'dropout': 0.2, 'class_weighting': 'sqrt_inverse'},
    'gnn-sage-edge': {'epochs': 150, 'batch_size': 4, 'lr': 5e-3, 'optimizer': 'adamw', 'weight_decay': 5e-4, 'scheduler': 'plateau',
                      'hidden': 96, 'layers': 3, 'dropout': 0.2, 'class_weighting': 'sqrt_inverse'},
}

SCHEMA = {
    'epochs': (int, 1, 2000), 'batch_size': (int, 1, 256), 'lr': (float, 1e-7, 1.0), 'weight_decay': (float, 0.0, 1.0),
    'training_scale': (float, 0.05, 2.0), 'crop_size': (int, 64, 2048), 'crops_per_sheet': (int, 1, 256),
    'hidden': (int, 8, 1024), 'layers': (int, 1, 8), 'heads': (int, 1, 16), 'dropout': (float, 0.0, 0.9),
    'seed': (int, 0, 2**31 - 1), 'early_stopping_patience': (int, 1, 1000), 'checkpoint_every': (int, 1, 1000),
    'val_every': (int, 1, 100), 'max_runtime_s': (int, 30, 7 * 24 * 3600), 'score_threshold': (float, 0.0, 1.0),
}
ENUMS = {'optimizer': {'adamw', 'adam', 'sgd'}, 'scheduler': {'cosine', 'step', 'plateau', 'none'},
         'class_weighting': {'none', 'inverse', 'sqrt_inverse'}}
AUGMENTS = {'flip', 'rot90', 'brightness', 'noise'}
GPU_FOR = {'cv': 'nvidia-t4', 'gnn': 'cpu'}


class ConfigError(ValueError):
    pass


def recommended(catalog_id: str, dataset_stats: dict | None = None) -> dict:
    if catalog_id not in DEFAULTS:
        raise ConfigError(f'No training template for {catalog_id}')
    cfg = {**copy.deepcopy(COMMON), **copy.deepcopy(DEFAULTS[catalog_id])}
    n = (dataset_stats or {}).get('train_items')
    if n is not None and n < 20 and catalog_id.startswith(('seg-', 'inst-')):
        cfg['crops_per_sheet'] = max(cfg['crops_per_sheet'], 12)  # small datasets: more crops/epoch
    return cfg


def validate(catalog_id: str, overrides: dict | None) -> dict:
    cfg = recommended(catalog_id)
    allowed = set(cfg) | ({'_fault'} if os.environ.get('KA_ALLOW_FAULT_INJECTION') == '1' else set())
    for k, v in (overrides or {}).items():
        if k not in allowed:
            raise ConfigError(f'Unsupported hyperparameter "{k}" for {catalog_id}')
        if k == '_fault':
            cfg[k] = v
            continue
        if k in SCHEMA:
            typ, lo, hi = SCHEMA[k]
            try:
                v = typ(v)
            except (TypeError, ValueError):
                raise ConfigError(f'{k} must be {typ.__name__}')
            if not lo <= v <= hi:
                raise ConfigError(f'{k}={v} outside [{lo}, {hi}]')
        elif k in ENUMS:
            if v not in ENUMS[k]:
                raise ConfigError(f'{k} must be one of {sorted(ENUMS[k])}')
        elif k == 'augment':
            if not isinstance(v, list) or not set(v) <= AUGMENTS:
                raise ConfigError(f'augment must be a subset of {sorted(AUGMENTS)}')
        cfg[k] = v
    return cfg
