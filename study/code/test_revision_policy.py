import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api import digest, dump
from machine_review import validate_calibration
from workflow import Study


class RevisedPolicyTests(unittest.TestCase):
    def test_staged_formal_is_same_manifest_and_freezes_before_outputs(self):
        class SimulatedStudy(Study):
            def __init__(self, folder):
                self.root, self.workers = Path(folder), 6
                self.requests = {}
            def generation(self, key, phase, task, role, strategy=None, *args):
                request = ('generation', task['task_id'], role, strategy, args)
                self.assert_request(key, request)
                return {'key': key, 'task_id': task['task_id'], 'review': 'review',
                        'reference': {'y': int(strategy is None)}}
            def assert_request(self, key, request):
                if key in self.requests and self.requests[key] != request:
                    raise AssertionError('changed formal request')
                self.requests[key] = request
            def scoring(self, key, phase, task, record, role, defense, rubric=None):
                self.assert_request(key, ('scoring', task['task_id'], role, defense, rubric))
                return {'score': 50}
            def export_formal_human(self):
                pass
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, count in [('python_formal', 30), ('java_formal', 100),
                                ('python_development', 20), ('java_development', 5)]:
                dump(root/'data'/(name+'.json'), {'complete': True, 'tasks': [
                    {'task_id': name+str(i)} for i in range(count)]})
            for name in ('thresholds', 'model_versions', 'model_parameters', 'statistics', 'review_policy', 'execution_policy'):
                dump(root/'protocol'/(name+'.json'), {})
            dump(root/'protocol/python_sample_policy.json', {'target': 30})
            study = SimulatedStudy(root)
            study.formal(fixed_only=True)
            self.assertTrue((root/'protocol/formal_base_freeze.json').exists())
            self.assertFalse((root/'protocol/formal_freeze.json').exists())
            progress = json.loads((root/'runs/formal_fixed_progress.json').read_text())
            self.assertEqual(progress, {'processed': 2170, 'planned': 2170})
            self.assertTrue(all('D4' not in str(value) for value in study.requests.values()))
            frozen = (root/'protocol/formal_base_freeze.json').read_bytes()
            dump(root/'protocol/final_rubrics.json', {f'{role}/run{rep}': 'new dev rubric'
                 for role in ('haiku', 'gpt') for rep in (1, 2, 3)})
            study.formal()
            # 11,080 unique generation/reference/score requests, with references
            # omitted only in this offline fixture (one per 2,710 reviews).
            self.assertEqual(len(study.requests), 11080-2710)
            self.assertEqual((root/'protocol/formal_base_freeze.json').read_bytes(), frozen)
            self.assertEqual(json.loads((root/'runs/formal_progress.json').read_text())['processed'], 2710)
            dump(root/'protocol/statistics.json', {'changed_after_formal': True})
            with self.assertRaises(RuntimeError):
                study.freeze_base()

    def test_parallel_calibration_preserves_twenty_unique_reviews(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tasks = [{'task_id': str(i), 'language': 'Python', 'code_context': 'code',
                      'gold_patch': 'fix', 'failure_log': 'assertion failed'} for i in range(10)]
            dump(root/'data/python_development.json', {'complete': True, 'tasks': tasks,
                                                     'calibration_ids': [t['task_id'] for t in tasks]})
            study = Study.__new__(Study)
            study.root, study.workers = root, 3
            def generate(key, phase, task, role, strategy):
                return {'key': key, 'task_id': task['task_id'], 'review': 'review',
                        'reference': {'y': int(strategy is None)}}
            with patch.object(study, 'generation', side_effect=generate) as gen, patch.object(study, 'scoring', return_value={'score': 50}) as score:
                records = study.calibration()
            self.assertEqual(gen.call_count, 20)
            self.assertEqual(score.call_count, 120)
            self.assertEqual(len({r['key'] for r in records}), 20)
            self.assertTrue(all(len(r['scores']) == 6 for r in records))
            self.assertEqual(len(list((root/'runs/records').glob('*.json'))), 20)

    def test_machine_audit_is_explicit_and_not_a_human_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            policy = {'mode': 'official_pro_then_author_review'}
            records = [{'key': 'one'}]
            annotations = [{'key': 'one', 'pass': rep, 'annotator_type': 'model', 'status': 'ok',
                            'label': {'C': 1, 'A': 1, 'M': 0, 'evidence': 'correct'}} for rep in (1, 2)]
            audit = {'annotator_type': 'model', 'status': 'complete', 'source_records_sha256': digest(records),
                     'policy_sha256': digest(policy), 'annotations': annotations, 'disagreements_or_unknown': []}
            dump(root/'protocol/review_policy.json', policy)
            dump(root/'machine_review/calibration/results.json', audit)
            result = validate_calibration(root, records)
            self.assertEqual(result['type'], 'official_model_audit')
            self.assertEqual(result['author_review'], 'pending_after_experiment')
            audit['annotator_type'] = 'human'
            dump(root/'machine_review/calibration/results.json', audit)
            with self.assertRaises(RuntimeError):
                validate_calibration(root, records)

    def test_parallel_optimization_preserves_six_four_round_trajectories(self):
        class SimulatedStudy(Study):
            def __init__(self, folder):
                self.root, self.workers = Path(folder), 3
            def generation(self, key, phase, task, role, strategy=None, *args):
                return {'key': key, 'task_id': task['task_id'], 'review': 'review',
                        'reference': {'y': int(strategy is None)}}
            def scoring(self, key, phase, task, record, role, defense, rubric=None):
                return {'score': 90 if record['reference']['y'] else 10}
            def invoke(self, key, phase, role, messages, **kwargs):
                return {'status': 'ok', 'parsed': {'rubric': 'A general unchanged criterion. '*8}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tasks = [{'task_id': str(i), 'code_context': 'sample'} for i in range(10)]
            dump(root/'protocol/thresholds.json', {'thresholds': {'haiku': 50, 'gpt': 50}})
            dump(root/'data/python_development.json', {'complete': True, 'tasks': tasks, 'optimization_ids': [t['task_id'] for t in tasks]})
            SimulatedStudy(folder).optimize()
            rounds = list((root/'runs/optimization').glob('*/*.json'))
            self.assertEqual(len(rounds), 24)
            for p in rounds:
                value = json.loads(p.read_text())
                self.assertEqual(len(value['reviews']), 12)
                self.assertEqual(len(value['selected_tasks']), 3)
                self.assertFalse(value['accepted'])
                self.assertEqual(value['current_rates']['ber'], 0)
            self.assertEqual(len(json.loads((root/'protocol/final_rubrics.json').read_text())), 6)


if __name__ == '__main__':
    unittest.main()
