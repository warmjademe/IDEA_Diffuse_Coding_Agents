"""Offline checks for conclusions, leakage, parsing, and budget integrity."""
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from api import Runner, BudgetStop, MODELS, dump, parse_score, parse_reference
from workflow import threshold_for, score_rates, accept_candidate
from prepare_python import context_from_patch, normalize_patch
import prompts


class ProtocolTests(unittest.TestCase):
    def test_unparseable_score_is_not_imputed(self):
        for text in ('I cannot judge this.', '{"score":101}', '{"score":"85"}', '{"score":true}'):
            with self.assertRaises(ValueError):
                parse_score(text)

    def test_reference_intent_is_not_a_label(self):
        self.assertEqual(parse_reference('{"C":1,"A":1,"M":0,"evidence":"correct"}')["y"], 1)
        self.assertIsNone(parse_reference('{"C":1,"A":"unknown","M":0,"evidence":"unclear"}')["y"])
        self.assertEqual(parse_reference('{"C":1,"A":1,"M":1,"evidence":"misleading"}')["y"], 0)

    def test_threshold_and_degenerate_optimization(self):
        labels = [1]*5+[0]*3
        scores = [20, 50, 70, 80, 90, 30, 70, 90]
        self.assertEqual(threshold_for(labels, scores), 50)
        current = score_rates(labels, scores, 50)
        reject_all = score_rates(labels, [0]*8, 50)
        self.assertFalse(accept_candidate(current, reject_all))
        self.assertFalse(accept_candidate(current, current))
        self.assertFalse(accept_candidate(None, None))

    def test_pairing_is_balanced_and_unique(self):
        panel = [(i, k, c, 1+(i+k+c)%3) for i in range(30) for k in range(3) for c in range(2)]
        self.assertEqual(len(set(panel)), 180)
        self.assertEqual([sum(x[3] == r for x in panel) for r in (1, 2, 3)], [60]*3)
        self.assertEqual(180*3*2-180, 900)

    def test_checker_never_receives_gold(self):
        task = {"language": "Python", "code_context": "BUGGY_CODE", "gold_patch": "SECRET_FIX",
                "hidden_defect": {"issue": "SECRET_ISSUE"}, "failure_log": "RAW_LOG"}
        d1, d5 = (prompts.checker(task, "REVIEW", d) for d in ("D1", "D5"))
        for msgs in (d1, d5, prompts.benign(task)):
            self.assertNotIn("SECRET", json.dumps(msgs))
        a, b = json.loads(d1[1]["content"]), json.loads(d5[1]["content"])
        self.assertEqual(b.pop("test_failure_log"), "RAW_LOG")
        self.assertEqual(a, b)
        self.assertEqual(d1[0], d5[0])

    def test_collected_patch_headers_and_preimage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"f.py").write_text("def f():\n    return 0\n")
            raw = "diff --git a/f.py b/f.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 0\n+    return 1\n"
            normalized = normalize_patch(raw, root)
            self.assertIn("--- a/f.py\n+++ b/f.py\n", normalized)
            context = context_from_patch(root, raw)
            self.assertIn("return 0", context)
            self.assertNotIn("return 1", context)
            newfile = "diff --git a/new.py b/new.py\n@@ -0,0 +1 @@\n+value = 1\n"
            patchfile = root/"new.patch"
            patchfile.write_text(normalize_patch(newfile, root))
            result = subprocess.run(["git", "apply", "--recount", str(patchfile)], cwd=root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root/"new.py").read_text(), "value = 1\n")


class LedgerTests(unittest.TestCase):
    @patch.dict("os.environ", {"TEAMOROUTER_API_KEY": "unit-test-placeholder"})
    @patch.object(Runner, 'transport')
    def test_cache_phase_and_budget(self, api_call):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dump(root/"protocol/budget.json", {"usd_cap": 5, "allowed_phases": ["pilot"]})
            prices = {"models": [{"id": name, "list_cost": {"input": 1, "output": 1},
                                   "cost": {"input": 1, "output": 1}} for name in MODELS.values()]}
            dump(root/"protocol/pricing_snapshot.json", prices)
            api_call.return_value = {'response': {'model': MODELS['haiku'],
                'choices': [{'message': {'content': '{"score":55}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 4}}}
            runner = Runner(root)
            messages = [{"role": "user", "content": "test"}]
            one = runner.call("job", "pilot", "haiku", messages, parser=parse_score)
            two = runner.call("job", "development", "haiku", messages, parser=parse_score)
            self.assertEqual(one["id"], two["id"])
            self.assertEqual(api_call.call_count, 1)
            with self.assertRaises(BudgetStop):
                runner.call("formal-job", "formal", "haiku", messages)
            with self.assertRaises(RuntimeError):
                runner.call("job", "pilot", "haiku", [{"role": "user", "content": "changed"}])
            dump(root/"protocol/budget.json", {"usd_cap": 0, "allowed_phases": ["pilot"]})
            with self.assertRaises(BudgetStop):
                runner.call("over-budget", "pilot", "haiku", messages)
            self.assertEqual(api_call.call_count, 1)
            dump(root/"protocol/budget.json", {"usd_cap": None, "allowed_phases": ["pilot", "development"]})
            runner.call("uncapped-development", "development", "haiku", messages, parser=parse_score)
            self.assertEqual(api_call.call_count, 2)
            with self.assertRaises(BudgetStop):
                runner.call("uncapped-formal-still-gated", "formal", "haiku", messages)

    @patch.object(Runner, 'transport', side_effect=subprocess.TimeoutExpired('transport.py', 195))
    def test_wall_timeout_preserves_attempt_and_unknown_cost(self, transport):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dump(root/'protocol/budget.json', {'usd_cap': None, 'allowed_phases': ['formal']})
            dump(root/'protocol/pricing_snapshot.json', {'models': [
                {'id': MODELS['haiku'], 'list_cost': {'input': 1, 'output': 1},
                 'cost': {'input': 1, 'output': 1}}]})
            runner = Runner(root)
            result = runner.call('timeout', 'formal', 'haiku', [{'role': 'user', 'content': 'test'}])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error_type'], 'TimeoutExpired')
            self.assertNotIn('parsed', result)
            self.assertTrue((root/'runs/requests'/(result['id']+'.json')).exists())
            with runner.db() as db:
                row = db.execute('SELECT * FROM calls').fetchone()
                self.assertIsNone(row['estimated_usd'])
                self.assertGreater(row['reserved_usd'], 0)
                self.assertEqual(row['status'], 'failed')
            runner.call('timeout', 'formal', 'haiku', [{'role': 'user', 'content': 'test'}])
            self.assertEqual(transport.call_count, 1)


if __name__ == "__main__":
    unittest.main()
