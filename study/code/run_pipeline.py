"""Durable NAS coordinator for the authorized amended protocol."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

from api import clean_error, dump
from machine_review import evaluate, preflight
from workflow import Study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    if platform.node() != 'qyb-SJHY-ubuntu25':
        raise RuntimeError('experimental execution is authorized on NAS')
    root = Path(args.root)
    lock = (root/'runs/pipeline.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    study = Study(root, args.workers)
    state = {'started': time.time(), 'status': 'running', 'stage': 'waiting_for_existing_calibration',
             'completed_stages': [], 'author_check': 'pending_after_automatic_experiment'}

    def save():
        state['updated'] = time.time()
        dump(root/'runs/pipeline_state.json', state)

    def develop_and_run_fixed():
        # Independent namespaces; optimize reads only the development dataset.
        # Join both workers before formal() reuses fixed calls and adds D4.
        with ThreadPoolExecutor(max_workers=2) as pool:
            fixed = pool.submit(study.formal, fixed_only=True)
            optimization = pool.submit(study.optimize)
            optimization.result()
            fixed.result()

    try:
        save()
        while subprocess.run(['tmux', 'has-session', '-t', 'jsep-v3-calibration'], capture_output=True).returncode == 0:
            if (root/'STOP').exists():
                raise RuntimeError('STOP file exists')
            time.sleep(5)
        actions = [
            ('calibration', study.calibration),
            ('official_pro_preflight', lambda: preflight(study)),
            ('official_pro_calibration', lambda: evaluate(study, 'calibration')),
            ('thresholds', study.freeze_thresholds),
            ('base_freeze', study.freeze_base),
            ('formal_fixed_and_development_D4', develop_and_run_fixed),
            ('freeze', study.freeze_formal),
            ('formal', study.formal),
            ('official_pro_formal', lambda: evaluate(study, 'formal')),
            ('analysis', lambda: subprocess.run([sys.executable, str(Path(__file__).with_name('analyze.py')),
                                                 '--root', str(root)], check=True)),
        ]
        for stage, action in actions:
            if (root/'STOP').exists():
                raise RuntimeError('STOP file exists')
            state['stage'] = stage
            save()
            action()
            state['completed_stages'].append(stage)
            dump(root/'runs/usage_summary.json', study.api.summary())
            save()
        state.update(status='automatic_experiment_finished_awaiting_author_check', finished=time.time())
        save()
    except Exception as error:
        state.update(status='stopped_requires_attention', error_type=type(error).__name__, error=clean_error(error))
        save()
        (root/'logs/pipeline_error.log').write_text(clean_error(traceback.format_exc()))
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    main()
