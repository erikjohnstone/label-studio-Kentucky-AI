"""Training container entrypoint. Identical on every compute provider.

    python -m kentucky.training.runner /path/to/job_dir

``job_dir/spec.json`` contains: job_id, task, catalog_id, init, config, bundle_dir, out_dir,
base_checkpoint?, max_runtime_s. Progress is written to ``job_dir/events.jsonl``; a file named
``CANCEL`` in job_dir requests cancellation. The runner never touches the application database
(training worker isolation): the orchestrator reads events and artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path


def run(job_dir: str) -> int:
    job_dir = str(Path(job_dir).resolve())
    spec = json.loads(Path(job_dir, 'spec.json').read_text())
    from .events import Cancelled, Reporter

    rep = Reporter(os.path.join(job_dir, 'events.jsonl'))
    spec['job_dir'] = job_dir
    spec.setdefault('out_dir', os.path.join(job_dir, 'artifacts'))
    deadline = time.time() + float(spec.get('max_runtime_s') or spec['config'].get('max_runtime_s', 3600))
    try:
        import torch

        torch.set_num_threads(max(1, int(os.environ.get('KA_TORCH_THREADS', os.cpu_count() or 1))))
        rep.status('PREPARING', torch=torch.__version__, device='cuda' if torch.cuda.is_available() else 'cpu',
                   pid=os.getpid())
        if spec['task'] == 'semantic_segmentation':
            from .cv import train_semantic as fn
        elif spec['task'] == 'instance_segmentation':
            from .cv import train_instance as fn
        elif spec['task'] in ('node_classification', 'edge_classification'):
            from .gnn import train_gnn as fn
        else:
            raise ValueError(f'unknown task {spec["task"]}')
        t0 = time.time()
        final, best = fn(spec, rep, deadline)
        rep.status('SAVING')
        sha = hashlib.sha256(Path(best).read_bytes()).hexdigest()
        final['train_seconds'] = round(time.time() - t0, 2)
        Path(spec['out_dir'], 'metrics.json').write_text(json.dumps(final, default=float, indent=1))
        rep.emit('final', metrics=final, artifact=str(Path(best).relative_to(job_dir)), sha256=sha)
        return 0
    except Cancelled:
        rep.emit('cancelled')
        return 3
    except TimeoutError as e:
        rep.emit('timeout', message=str(e))
        return 4
    except Exception as e:  # noqa: BLE001
        rep.emit('error', message=f'{type(e).__name__}: {e}', traceback=traceback.format_exc()[-4000:])
        return 1


if __name__ == '__main__':
    sys.exit(run(sys.argv[1]))
