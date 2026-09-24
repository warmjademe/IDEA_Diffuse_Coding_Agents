"""Independent NAS supervisor: diagnose 30-minute stalls and resume cached work."""
import argparse
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

from api import clean_error, dump


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def cpu_ticks(pid):
    """Include an analysis subprocess, while avoiding unrelated host workloads."""
    try:
        directory = Path('/proc')/str(pid)
        fields = (directory/'stat').read_text().rsplit(')', 1)[1].split()
        children = (directory/'task'/str(pid)/'children').read_text().split()
        return int(fields[11])+int(fields[12])+sum(cpu_ticks(int(p)) for p in children)
    except (OSError, ValueError, IndexError):
        return 0


def progress(root, pid=None):
    root = Path(root)
    result = {}
    with closing(sqlite3.connect(root/'runs/ledger.sqlite', timeout=5)) as db:
        result['successful_calls'] = db.execute("SELECT count(*) FROM calls WHERE status='ok'").fetchone()[0]
    for name in ('formal_fixed_progress', 'formal_progress'):
        result[name] = read_json(root/'runs'/(name+'.json')).get('processed', 0)
    for stage in ('calibration', 'formal'):
        result['pro_'+stage] = read_json(root/'machine_review'/stage/'progress.json').get('processed', 0)
    result['d4_rounds'] = len(list((root/'runs/optimization').glob('*/*.json')))
    state = read_json(root/'runs/pipeline_state.json')
    result['completed_stages'] = len(state.get('completed_stages', []))
    if state.get('stage') == 'analysis' and pid:
        result['analysis_cpu_ticks'] = cpu_ticks(pid)
    return result


def advanced(highwater, observed):
    # Replaying cached stages, new reservations, failures alone, and a heartbeat
    # do not reset the timer. Completed jobs and valid responses do.
    changed = any(value > highwater.get(key, 0) for key, value in observed.items())
    for key, value in observed.items():
        highwater[key] = max(highwater.get(key, 0), value)
    return changed


def notify(root, title, body):
    private = Path.home()/'.config/jsep-diffuse/bark.endpoint'
    endpoint = os.environ.get('BARK_ENDPOINT') or (private.read_text().strip() if private.exists() else None)
    if not endpoint:
        return
    try:
        request = urllib.request.Request(endpoint, data=json.dumps(
            {'title': title, 'body': body, 'group': 'JSEP 实验监测'}, ensure_ascii=False).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except Exception as error:
        dump(Path(root)/'runs/watchdog_notification_error.json',
             {'time': time.time(), 'type': type(error).__name__})


def diagnose(root, pid, reason):
    root = Path(root)
    out = root/'runs/watchdog_incidents'/str(time.time_ns())
    out.mkdir(parents=True)
    state = read_json(root/'runs/pipeline_state.json')
    log = root/'logs/pipeline.log'
    if log.exists():
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size-24000))
            tail = stream.read().decode(errors='replace')
        (out/'pipeline_tail.txt').write_text(clean_error(tail))
    traces = ''
    spy = root/'ops/debug_tools/bin/py-spy'
    commands = []
    if spy.exists():
        commands.append(('python_stacks.txt', ['sudo', '-n', str(spy), 'dump', '--pid', str(pid)]))
    commands.append(('native_stacks.txt', ['sudo', '-n', 'gdb', '-q', '-batch', '-p', str(pid),
                    '-ex', 'set print frame-arguments none', '-ex', 'thread apply all bt 18', '-ex', 'detach']))
    if Path('/proc', str(pid)).exists():
        for name, command in commands:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=40)
                # No locals or C frame arguments are requested by either probe.
                text = result.stdout+result.stderr
                (out/name).write_text(text)
                traces += text
            except Exception as error:
                (out/name).write_text(type(error).__name__)
    with closing(sqlite3.connect(root/'runs/ledger.sqlite', timeout=5)) as db:
        db.row_factory = sqlite3.Row
        pending = [dict(row) for row in db.execute("SELECT id,logical_id,role,attempt,started FROM calls WHERE status='reserved'")]
    if 'findReusableFd' in traces and ('sqlite3WalClose' in traces or 'unixLock' in traces):
        category = 'sqlite_connection_lifecycle_deadlock'
    elif pending:
        category = 'incomplete_model_calls_or_scheduler_stall'
    else:
        category = 'worker_exit_or_scheduler_stall'
    dump(out/'diagnosis.json', {'time': time.time(), 'reason': reason, 'category': category,
                              'pid': pid, 'pipeline': state, 'pending': pending})
    return out, category


def stop_worker(process):
    # Each worker and its transport children have a dedicated process group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=10)


def recover_interrupted(root, incident):
    """After worker termination only: preserve rows, attempts and unknown costs."""
    root, incident = Path(root), Path(incident)
    recovered = []
    with closing(sqlite3.connect(root/'runs/ledger.sqlite', timeout=10)) as db:
        db.row_factory = sqlite3.Row
        with closing(sqlite3.connect(incident/'ledger_before_recovery.sqlite')) as backup:
            db.backup(backup)
        for row in list(db.execute("SELECT * FROM calls WHERE status='reserved'")):
            artifact = Path(row['artifact'])
            if artifact.exists():
                result = read_json(artifact)
                if result.get('id') != row['id'] or result.get('request_hash') != row['request_hash']:
                    raise RuntimeError('reserved artifact identity mismatch')
                action = 'reconciled_saved_response'
            else:
                result = read_json(root/'runs/requests'/(row['id']+'.json'))
                result.update({k: row[k] for k in ('id', 'logical_id', 'phase', 'role', 'attempt', 'request_hash', 'reserved_usd', 'started')})
                result.update(status='failed', error_type='InterruptedByWatchdog',
                              error='Worker stopped after diagnosed loss of progress. Upstream completion and billing unknown.',
                              estimated_usd=None, ended=time.time(),
                              watchdog_incident=str(incident.relative_to(root)))
                dump(artifact, result)
                action = 'interrupted_attempt_retained'
            if result.get('status') not in ('ok', 'failed'):
                raise RuntimeError('saved response is not terminal')
            db.execute('UPDATE calls SET status=?,estimated_usd=?,ended=?,returned_model=? WHERE id=?',
                       (result['status'], result.get('estimated_usd'), result.get('ended', time.time()),
                        result.get('raw_response', {}).get('model'), row['id']))
            recovered.append({'id': row['id'], 'attempt': row['attempt'], 'action': action})
        db.commit()
    dump(incident/'recovery.json', {'time': time.time(), 'calls': recovered,
                                  'retry_counts_reset': False, 'model_calls_made': 0})
    return recovered


def supervise(root, command, idle_seconds=1800, poll_seconds=30, max_restarts=3):
    root = Path(root)
    highwater = progress(root)
    retries = 0
    while True:
        if (root/'STOP').exists():
            dump(root/'runs/watchdog_state.json', {'status': 'paused_by_STOP', 'updated': time.time()})
            return
        with (root/'logs/pipeline.log').open('a') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        launched = last_progress = time.time()
        successes_at_launch = highwater.get('successful_calls', 0)
        failure = None
        while True:
            now = time.time()
            state = read_json(root/'runs/pipeline_state.json')
            try:
                observed = progress(root, process.pid)
                if advanced(highwater, observed):
                    last_progress = now
                sample_error = None
            except Exception as error:
                sample_error = type(error).__name__
            status = {'status': 'monitoring', 'pid': os.getpid(), 'worker_pid': process.pid,
                      'updated': now, 'last_progress': last_progress, 'idle_seconds': round(now-last_progress),
                      'stall_threshold_seconds': idle_seconds, 'poll_seconds': poll_seconds,
                      'highwater': highwater, 'consecutive_recoveries': retries, 'sampling_error': sample_error}
            dump(root/'runs/watchdog_state.json', status)
            returncode = process.poll()
            if returncode is not None:
                if returncode == 0 and state.get('status') == 'automatic_experiment_finished_awaiting_author_check':
                    dump(root/'runs/watchdog_state.json', {**status, 'status': 'automatic_experiment_finished_awaiting_author_check'})
                    notify(root, 'JSEP 自动评测阶段结束', '自动评测与统计已结束，仍需作者人工校对及论文修订；尚非论文修订任务全部完成。')
                    return
                if (root/'STOP').exists():
                    dump(root/'runs/watchdog_state.json', {**status, 'status': 'paused_by_STOP'})
                    return
                failure = 'worker_exit_'+str(returncode)
                break
            if now-last_progress >= idle_seconds:
                failure = 'no_actual_progress_for_'+str(idle_seconds)+'_seconds'
                break
            time.sleep(poll_seconds)
        incident, category = diagnose(root, process.pid, failure)
        stop_worker(process)
        recover_interrupted(root, incident)
        state = read_json(root/'runs/pipeline_state.json')
        error = str(state.get('error', '')).lower()
        protected = any(text in error for text in ('immutable', 'freeze', 'frozen', 'amendment',
                        'threshold', 'call ceiling', 'monetary ceiling', 'phase gate', 'dataset not complete'))
        if highwater.get('successful_calls', 0)-successes_at_launch >= 25:
            retries = 0
        retries += 1
        halt = protected or retries > max_restarts
        state.update(status='stopped_requires_attention' if halt else 'recovering_after_diagnosed_stall',
                     updated=time.time(), watchdog_incident=str(incident.relative_to(root)))
        dump(root/'runs/pipeline_state.json', state)
        dump(root/'runs/watchdog_state.json', {'status': 'needs_attention' if halt else 'restarting',
             'updated': time.time(), 'reason': failure, 'diagnosis': category,
             'incident': str(incident.relative_to(root)), 'consecutive_recoveries': retries})
        notify(root, 'JSEP 实验监测：'+('需要排查' if halt else '自动断点恢复'),
               '检测到 '+failure+'；诊断 '+category+'。日志、堆栈及调用账本已保存。'+
               ('已保留现场，未更改冻结方案或追加重试预算。' if halt else '正在复用已有结果继续实验，不重置调用次数。'))
        if halt:
            return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    root = Path(args.root)
    lock = (root/'runs/watchdog.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    command = [sys.executable, '-u', str(Path(__file__).with_name('run_pipeline.py')),
               '--root', str(root), '--workers', str(args.workers)]
    try:
        supervise(root, command)
    except Exception as error:
        dump(root/'runs/watchdog_state.json', {'status': 'watchdog_error', 'updated': time.time(),
                                              'error': clean_error(error)})
        notify(root, 'JSEP 监控异常', '监控程序需要排查：'+type(error).__name__+'；实验完成状态未确认。')
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    main()
