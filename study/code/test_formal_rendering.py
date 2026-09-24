import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api import digest, dump
from formal_rendering import recover_review_format
from workflow import Study


class FormalRenderingTests(unittest.TestCase):
    def test_amendment_preserves_original_freeze_and_scientific_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            study = Study.__new__(Study)
            study.root = root
            for name, count in [('python_formal', 30), ('java_formal', 100),
                                ('python_development', 20), ('java_development', 5)]:
                dump(root/'data'/(name+'.json'), {'complete': True, 'tasks': [
                    {'task_id': name+str(i)} for i in range(count)]})
            for name in ('thresholds', 'model_versions', 'model_parameters', 'statistics', 'review_policy', 'execution_policy'):
                dump(root/'protocol'/(name+'.json'), {})
            dump(root/'protocol/python_sample_policy.json', {'target': 30})
            dump(root/'protocol/final_rubrics.json', {'haiku/run1': 'fixed development rubric'})
            current = study.freeze_base()
            original = {**current, 'source': {'workflow.py': 'archived original source hash'}}
            base = root/'protocol/formal_base_freeze.json'
            dump(base, original)
            original_bytes = base.read_bytes()
            amendment = {'base_freeze_sha256': digest(original), 'source_before': original['source'],
                         'source_after': current['source'], 'completed_d4_rubrics_sha256':
                         digest({'haiku/run1': 'fixed development rubric'})}
            dump(root/'protocol/execution_amendment_01.json', amendment)
            amended = study.freeze_base()
            self.assertEqual(amended['base_freeze_sha256'], digest(original))
            self.assertEqual(base.read_bytes(), original_bytes)
            # A second repair must link to the first source snapshot exactly.
            intermediate = {'workflow.py': 'first repair source'}
            amendment['source_after'] = intermediate
            dump(root/'protocol/execution_amendment_01.json', amendment)
            second = {**amendment, 'source_before': intermediate, 'source_after': current['source']}
            dump(root/'protocol/execution_amendment_02.json', second)
            study.freeze_formal()
            self.assertTrue((root/'protocol/formal_freeze_revision_02.json').exists())
            self.assertEqual(base.read_bytes(), original_bytes)
            dump(root/'protocol/thresholds.json', {'changed': True})
            with self.assertRaisesRegex(RuntimeError, 'scientific input changed'):
                study.freeze_base()
            dump(root/'protocol/thresholds.json', {})
            dump(root/'protocol/final_rubrics.json', {'haiku/run1': 'changed'})
            with self.assertRaisesRegex(RuntimeError, 'D4 rubrics changed'):
                study.freeze_base()

    def test_nested_text_body_and_envelope_metadata_are_retained(self):
        for body_key in ('text', 'body', 'comment'):
            original = {'language': 'Java', 'review': {'summary': 'Consider this nonblocking.',
                'comments': [{'id': 7, 'file': 'A.java', 'lines': '4-7', 'severity': 'minor',
                              body_key: 'Exact review text.\nDo not rephrase it.', 'fix': 'keep as is'}]},
                'overall_assessment': 'Approve.'}
            rendered = recover_review_format(json.dumps(original))
            self.assertIn('1. Exact review text.\nDo not rephrase it.', rendered)
            for value in ('Consider this nonblocking.', 'A.java', '4-7', 'minor', 'keep as is', 'Approve.'):
                self.assertIn(value, rendered)
            self.assertIn('"id": 7', rendered)
            self.assertIn('"language": "Java"', rendered)
            self.assertIn('1. Exact review text.', recover_review_format(json.dumps(
                {'review_comments': original['review']['comments']})))

    def test_numbered_markdown_and_code_comments_remain_verbatim(self):
        for original in ('## Review\n\n**1.** Comment text.', '```java\n// 1. Comment text.\n```'):
            self.assertEqual(recover_review_format(original), original)
        for original in ('I cannot help.', '{"review":{"comments":[]}}',
                         '{"comments":[{"severity":"high"}]}', '{invalid JSON'):
            self.assertIsNone(recover_review_format(original))

    def test_repair_only_applies_to_previously_rejected_formal_attacks(self):
        nested = '{"review":{"comments":[{"body":"Review body."}]}}'
        with tempfile.TemporaryDirectory() as folder:
            study = Study.__new__(Study)
            study.root = Path(folder)
            task = {'task_id': 't', 'language': 'Java', 'code_context': 'code',
                    'gold_patch': 'patch', 'hidden_defect': {}, 'failure_log': 'log'}
            def respond(key, phase, role, messages, **kwargs):
                return {'id': key, 'status': 'ok', 'content': nested,
                        'parsed': {'C': 1, 'A': 1, 'M': 0, 'y': 1}}
            with patch.object(study, 'invoke', side_effect=respond):
                development = study.generation('development/t', 'development', task, 'sonnet', 'omission')
                formal = study.generation('formal/t', 'formal', task, 'sonnet', 'omission')
                benign = study.generation('formal/benign', 'formal', task, 'sonnet')
            self.assertEqual(development['status'], 'invalid_fixture_format')
            self.assertEqual(formal['review'], '1. Review body.')
            self.assertEqual(formal['review_rendering'], 'formal_presentation_recovery_v1')
            self.assertEqual(benign['review'], nested)


if __name__ == '__main__':
    unittest.main()
