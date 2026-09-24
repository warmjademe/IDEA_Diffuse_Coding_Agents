import unittest
from collections import Counter

from analyze import association, bh_adjust, metric_vectors, paired_contrast, summarize
from design import formal_jobs, human_sample
from workflow import review_text


def row(y, score, project='p', task='t'):
    return {'y': y, 'score': score, 'threshold': 50, 'project': project, 'task_id': task,
            'generated': True, 'weight': 1, 'strategy': 'omission', 'repetition': 1}


class AnalysisTests(unittest.TestCase):
    def test_manifest_matches_approved_budget(self):
        jobs = formal_jobs([{'task_id': f'py{i}'} for i in range(30)],
                           [{'task_id': f'java{i}'} for i in range(100)])
        self.assertEqual(len(jobs), 2710)
        self.assertEqual(sum(2+len(j['scores']) for j in jobs), 11080)
        self.assertEqual(len({j['key'] for j in jobs}), len(jobs))
        self.assertEqual(sum(j['paired_panel'] and j['language'] == 'Python' for j in jobs), 180)
        sample = human_sample(jobs)
        self.assertEqual(len(sample['selected']), 200)
        self.assertEqual(len({s['key'] for s in sample['selected']}), 200)
        self.assertTrue({s['key'] for s in sample['selected']} <= {j['key'] for j in jobs})
        self.assertEqual(Counter(s['inclusion_probability'] for s in sample['selected']),
                         Counter({1/3: 30, 1/18: 90, .2: 20, .2/3: 60}))
        self.assertEqual(sample, human_sample(jobs[::-1]))

    def test_labels_control_class_denominators(self):
        rows = [row(0, 90), row(1, 90), row(None, 90), row(0, None)]
        n, d = metric_vectors(rows, 'fpr')
        self.assertEqual(list(n), [1, 0, 0, 0])
        self.assertEqual(list(d), [1, 0, 0, 0])
        result = summarize(rows, 'missingness', 20)
        self.assertEqual(result['all_requested_joint_bounds'], [.25, .75])
        self.assertEqual(result['labeled'], 3)

    def test_tied_auc_and_constant_correlation(self):
        rows = [row(0, 1), row(0, 2), row(1, 2), row(1, 3)]
        self.assertEqual(association(rows, 'auroc'), .875)
        self.assertIsNone(association([row(0, 85), row(1, 85)], 'spearman'))
        self.assertIsNone(association([row(0, 85)], 'auroc'))

    def test_cluster_permutation_does_not_count_duplicate_reviews_as_projects(self):
        pairs = [(row(0, 100, p, p+str(i)), row(0, 0, p, p+str(i)))
                 for p in ('p1', 'p2') for i in range(10)]
        result = paired_contrast(pairs, 'fpr', 'cluster_check', 100)
        self.assertEqual(result['difference'], 1)
        self.assertEqual(result['projects'], 2)
        self.assertEqual(result['p'], .5)
        self.assertEqual(result['valid_permutations'], 4)

    def test_bh_preserves_unavailable_prespecified_hypotheses(self):
        tests = bh_adjust([{'p': .01}, {'p': .04}, {'p': None}])
        self.assertAlmostEqual(tests[0]['q_bh'], .03)
        self.assertAlmostEqual(tests[1]['q_bh'], .06)
        self.assertIsNone(tests[2]['q_bh'])

    def test_json_wrapper_only_is_removed(self):
        self.assertEqual(review_text('{"comments":[{"line":2,"comment":"Issue text."}],"file":"a.py"}'),
                         '1. a.py:2: Issue text.')
        self.assertEqual(review_text('1. Exact original text.'), '1. Exact original text.')
        rendered = review_text('{"review":[{"location":"a.py:3","text":"Fix this.","severity":"high"}]}')
        self.assertTrue(rendered.startswith('1. a.py:3: Fix this.'))
        self.assertIn('"severity": "high"', rendered)


if __name__ == '__main__':
    unittest.main()
