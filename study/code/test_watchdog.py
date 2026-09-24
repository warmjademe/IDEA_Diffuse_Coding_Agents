from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from api import Runner, dump
from watchdog import advanced, recover_interrupted, supervise


class WatchdogTests(unittest.TestCase):
    def test_concurrent_ledger_writes_keep_every_record(self):
        with tempfile.TemporaryDirectory() as folder:
            # Both instances must share the lifecycle guard.
            runners = [Runner(folder), Runner(folder)]
            def write(index):
                with runners[index % 2].db() as db:
                    db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (str(index), str(index), 'formal', 'haiku', 0, 'hash', 'ok',
                         .01, .001, 1., 2., 'unused', 'model'))
            with ThreadPoolExecutor(max_workers=32) as pool:
                list(pool.map(write, range(2000)))
            with runners[0].db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM calls').fetchone()[0], 2000)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_highwater_ignores_cache_replay(self):
        highwater = {'successful_calls': 203, 'formal_fixed_progress': 54}
        self.assertFalse(advanced(highwater, {'successful_calls': 203, 'formal_fixed_progress': 12}))
        self.assertFalse(advanced(highwater, {'successful_calls': 203, 'formal_fixed_progress': 54}))
        self.assertTrue(advanced(highwater, {'successful_calls': 204, 'formal_fixed_progress': 12}))
        self.assertEqual(highwater['formal_fixed_progress'], 54)

    def test_recovery_preserves_saved_response_and_unknown_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runner = Runner(root)
            incident = root/'runs/watchdog_incidents/test'
            incident.mkdir(parents=True)
            for key in ('saved', 'interrupted'):
                artifact = root/'runs/raw'/(key+'.json')
                with runner.db() as db:
                    db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (key, key, 'formal', 'haiku', 1, 'hash', 'reserved', .05,
                         None, 1., None, str(artifact), None))
            dump(root/'runs/raw/saved.json', {'id': 'saved', 'request_hash': 'hash',
                 'status': 'ok', 'estimated_usd': .02, 'ended': 2., 'raw_response': {'model': 'model'}})
            recovery = recover_interrupted(root, incident)
            self.assertEqual(len(recovery), 2)
            with runner.db() as db:
                rows = {row['id']: dict(row) for row in db.execute('SELECT * FROM calls')}
            self.assertEqual(rows['saved']['status'], 'ok')
            self.assertEqual(rows['saved']['estimated_usd'], .02)
            self.assertEqual(rows['interrupted']['status'], 'failed')
            self.assertIsNone(rows['interrupted']['estimated_usd'])
            self.assertEqual(rows['interrupted']['reserved_usd'], .05)
            self.assertEqual(rows['interrupted']['attempt'], 1)

    def test_stalled_process_is_diagnosed_stopped_and_resumed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Runner(root)
            (root/'logs').mkdir()
            script = root/'fake_worker.py'
            script.write_text('''import pathlib,sys,json,time
r=pathlib.Path(sys.argv[1]);counter=r/'starts.txt'
n=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(n))
if n==1:
    (r/'runs/pipeline_state.json').write_text(json.dumps({'status':'running','stage':'formal'}))
    while True: time.sleep(1)
else:
    (r/'runs/pipeline_state.json').write_text(json.dumps({'status':'automatic_experiment_finished_awaiting_author_check'}))
''')
            def diagnosis(folder, pid, reason):
                out = root/'runs/watchdog_incidents/test'
                out.mkdir(parents=True)
                return out, 'simulated_stall'
            with patch('watchdog.diagnose', side_effect=diagnosis) as diagnose, patch('watchdog.notify'):
                supervise(root, [sys.executable, str(script), str(root)], idle_seconds=.4, poll_seconds=.05)
            self.assertEqual(diagnose.call_count, 1)
            self.assertEqual((root/'starts.txt').read_text(), '2')
            self.assertEqual(json.loads((root/'runs/watchdog_state.json').read_text())['status'],
                             'automatic_experiment_finished_awaiting_author_check')

    def test_user_stop_is_never_removed_or_restarted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Runner(root)
            (root/'STOP').write_text('author pause')
            with patch('watchdog.subprocess.Popen') as launch:
                supervise(root, ['unused'])
            launch.assert_not_called()
            self.assertEqual((root/'STOP').read_text(), 'author pause')


if __name__ == '__main__':
    unittest.main()
