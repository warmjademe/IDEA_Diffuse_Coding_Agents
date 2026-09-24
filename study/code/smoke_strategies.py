"""Bounded development-only check of the two non-omission strategies."""
import argparse
import json
from pathlib import Path

from api import dump
from workflow import Study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    root = Path(args.root)
    study = Study(root)
    pilot = json.loads((root/'runs/calibration_pilot.json').read_text())
    task_id = pilot[0]['task_id']
    task = json.loads((root/'work/python_v3'/task_id/'outcome.json').read_text())
    records = []
    for strategy in ('downplay', 'bury'):
        key = f'strategy_smoke/{task_id}/{strategy}'
        rec = study.generation(key, 'pilot', task, 'sonnet', strategy, 'D5')
        rec['scores'] = {f'haiku/{d}': study.scoring(key+f'/haiku/{d}', 'pilot', task, rec, 'haiku', d)
                         for d in ('D1', 'D5')}
        study.save_record(key, rec)
        records.append(rec)
    dump(root/'runs/strategy_smoke.json', records)
    dump(root/'runs/usage_summary.json', study.api.summary())


if __name__ == '__main__':
    main()
