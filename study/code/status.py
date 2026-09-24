"""Read-only progress snapshot: no model requests, no credential reads."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from api import dump


def snapshot(root):
    root = Path(root)
    report = {'observed_at_unix': time.time(), 'datasets': {}, 'formal_llm_started': False}
    for language in ('python', 'java'):
        for stage in ('development', 'formal'):
            name = language+'_'+stage
            final = root/'data'/(name+'.json')
            progress = root/'data'/(name+'_progress.json')
            source = final if final.exists() and json.loads(final.read_text()).get('complete') else progress
            if source.exists():
                value = json.loads(source.read_text())
                report['datasets'][name] = {'verified': len(value.get('tasks', [])),
                                           'attempted': len(value.get('attempts', [])),
                                           'complete': value.get('complete', False)}
    if (root/'runs/ledger.sqlite').exists():
        db = sqlite3.connect(root/'runs/ledger.sqlite')
        try:
            calls, estimated, committed = db.execute('SELECT count(*),sum(estimated_usd),sum(coalesce(estimated_usd,reserved_usd)) FROM calls').fetchone()
            report['model_calls'] = {'current_run': calls, 'prior_connectivity': 2,
                                     'total': calls+2, 'estimated_usd': estimated,
                                     'committed_usd_including_unknown_reservations': committed}
            report['formal_llm_started'] = bool(db.execute("SELECT count(*) FROM calls WHERE phase='formal'").fetchone()[0])
            report['formal_calls'] = [dict(zip(('status', 'n'), row)) for row in
                db.execute("SELECT status,count(*) FROM calls WHERE phase='formal' GROUP BY status")]
            last = db.execute('SELECT max(ended) FROM calls').fetchone()[0]
            report['seconds_since_last_call_returned'] = round(time.time()-last, 1) if last else None
        finally:
            db.close()
    report['gates_present'] = {name: (root/'protocol'/name).exists() for name in
                               ('thresholds.json', 'formal_base_freeze.json', 'final_rubrics.json', 'formal_freeze.json')}
    report['d4_completed_rounds'] = len(list((root/'runs/optimization').glob('*/*.json')))
    for name in ('formal_fixed_progress', 'formal_progress'):
        path = root/'runs'/(name+'.json')
        if path.exists():
            report[name] = json.loads(path.read_text())
    report['human_pilot_files_present'] = all((root/'human/calibration'/name).exists() for name in
                                             ('reviewer_1.json', 'reviewer_2.json', 'pilot_resolution.json'))
    policy = root/'protocol/review_policy.json'
    if policy.exists():
        report['review_policy'] = json.loads(policy.read_text())['mode']
        report['human_pilot_is_launch_requirement'] = False
        for stage in ('calibration', 'formal'):
            path = root/'machine_review'/stage/'results.json'
            report['official_pro_'+stage] = json.loads(path.read_text())['status'] if path.exists() else 'pending'
    pipeline = root/'runs/pipeline_state.json'
    if pipeline.exists():
        report['pipeline'] = json.loads(pipeline.read_text())
    watchdog = root/'runs/watchdog_state.json'
    if watchdog.exists():
        report['watchdog'] = json.loads(watchdog.read_text())
        report['watchdog']['heartbeat_age_seconds'] = round(time.time()-report['watchdog'].get('updated', 0), 1)
        pid = report['watchdog'].get('worker_pid')
        report['watchdog']['worker_process_exists'] = bool(pid and (Path('/proc')/str(pid)).exists())
    report['observed_execution_health'] = (
        'no_recent_model_returns_check_watchdog' if report.get('seconds_since_last_call_returned', 0) is not None
        and report.get('seconds_since_last_call_returned', 0) > 1800
        else 'recent_model_activity')
    report['budget'] = json.loads((root/'protocol/budget.json').read_text())
    report['formal_call_processing_complete'] = (root/'runs/formal_calls_finished.json').exists()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    value = snapshot(args.root)
    dump(Path(args.root)/'runs/status_snapshot.json', value)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
