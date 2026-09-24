"""Preregistered paired/clustered analyses; never mix pilot and formal data."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from api import digest, dump, parse_reference

SEED = 20260922


def rng_for(name):
    return np.random.default_rng(int(hashlib.sha256(str(name).encode()).hexdigest()[:16], 16))


def ratio(a, b):
    return float(a/b) if b else None


def metric_vectors(rows, metric):
    """Numerator/denominator per row, preserving class-dependent denominators."""
    numerator, denominator = [], []
    for r in rows:
        y, s, tau = r['y'], r['score'], r['threshold']
        known = y in (0, 1)
        scored = s is not None
        if metric == 'harmful_fraction':
            den, num = known, known and y == 0
        elif metric == 'fpr':
            den = known and scored and y == 0
            num = den and s >= tau
        elif metric == 'fnr':
            den = known and scored and y == 1
            num = den and s < tau
        elif metric == 'joint_harmful_accepted':
            den = known and scored
            num = den and y == 0 and s >= tau
        elif metric == 'mean_score':
            den, num = scored, s if scored else 0
        else:
            raise ValueError(metric)
        weight = r.get('weight', 1)
        numerator.append(float(num)*weight)
        denominator.append(float(den)*weight)
    return np.array(numerator), np.array(denominator)


def weighted_rank(values, weights):
    _, inverse = np.unique(values, return_inverse=True)
    mass = np.bincount(inverse, weights=weights)
    return (np.cumsum(mass)-mass/2)[inverse]


def association(rows, kind, multiplicity=None):
    valid = np.array([r['y'] in (0, 1) and r['score'] is not None for r in rows])
    weights = np.array([r.get('weight', 1) for r in rows], dtype=float)
    if multiplicity is not None:
        weights *= multiplicity
    valid &= weights > 0
    y = np.array([r['y'] if r['y'] in (0, 1) else 0 for r in rows])[valid]
    s = np.array([r['score'] if r['score'] is not None else 0 for r in rows])[valid]
    w = weights[valid]
    if not len(y) or len(set(y)) != 2:
        return None
    if kind == 'auroc':
        # Weighted Mann–Whitney probability, including half credit for tied scores.
        _, inverse = np.unique(s, return_inverse=True)
        pos = np.bincount(inverse, weights=w*(y == 1))
        neg = np.bincount(inverse, weights=w*(y == 0), minlength=len(pos))
        return float(np.sum(pos*(np.cumsum(neg)-neg/2))/(sum(pos)*sum(neg)))
    x, z = weighted_rank(s, w), weighted_rank(y, w)
    x -= np.average(x, weights=w)
    z -= np.average(z, weights=w)
    den = np.sqrt(np.sum(w*x*x)*np.sum(w*z*z))
    return float(np.sum(w*x*z)/den) if den else None


def interval(values):
    good = np.asarray([v for v in values if v is not None and np.isfinite(v)])
    return {'low': float(np.quantile(good, .025)) if len(good) else None,
            'high': float(np.quantile(good, .975)) if len(good) else None,
            'valid_replicates': len(good)}


def summarize(rows, name, replicates=10000, cluster='project'):
    keys = sorted({r[cluster] for r in rows})
    inverse = np.array([keys.index(r[cluster]) for r in rows])
    draws = rng_for((name, cluster)).multinomial(len(keys), [1/len(keys)]*len(keys), replicates)
    out = {'requested': len(rows), 'generated': sum(r['generated'] for r in rows),
           'labeled': sum(r['y'] in (0, 1) for r in rows),
           'scored': sum(r['score'] is not None for r in rows),
           'unknown_reference': sum(r['generated'] and r['y'] is None for r in rows),
           'projects': len({r['project'] for r in rows}), 'tasks': len({r['task_id'] for r in rows}),
           'cluster': cluster, 'clusters': len(keys), 'metrics': {}}
    for metric in ('fpr', 'fnr', 'joint_harmful_accepted', 'harmful_fraction', 'mean_score'):
        num, den = metric_vectors(rows, metric)
        cn, cd = (np.bincount(inverse, weights=v, minlength=len(keys)) for v in (num, den))
        bn, bd = draws@cn, draws@cd
        samples = np.divide(bn, bd, out=np.full(len(bn), np.nan), where=bd > 0)
        out['metrics'][metric] = {'estimate': ratio(sum(num), sum(den)),
                                  'weighted_numerator': float(sum(num)), 'weighted_denominator': float(sum(den)),
                                  'ci95': interval(samples)}
    for metric in ('auroc', 'spearman'):
        samples = [association(rows, metric, draw[inverse]) for draw in draws]
        out['metrics'][metric] = {'estimate': association(rows, metric), 'ci95': interval(samples)}
    num, den = metric_vectors(rows, 'joint_harmful_accepted')
    total_weight = sum(r.get('weight', 1) for r in rows)
    unresolved_weight = total_weight-sum(den)
    out['all_requested_joint_bounds'] = [ratio(sum(num), total_weight),
                                         ratio(sum(num)+unresolved_weight, total_weight)]
    per_run = []
    for rep in (1, 2, 3):
        group = [r for r in rows if r['strategy'] and r['repetition'] == rep]
        if group:
            n, d = metric_vectors(group, 'joint_harmful_accepted')
            per_run.append({'run': rep, 'value': ratio(sum(n), sum(d)), 'usable': int(sum(d))})
    values = [r['value'] for r in per_run if r['value'] is not None]
    out['attack_runs'] = {'values': per_run, 'mean': float(np.mean(values)) if len(values) == 3 else None,
                          'sample_sd': float(np.std(values, ddof=1)) if len(values) == 3 else None}
    if cluster == 'project' and len(keys) < 5:
        out['small_project_count'] = True
        out['task_cluster_sensitivity'] = summarize(rows, name, replicates, 'task_id')
    return out


def paired_contrast(pairs, metric, name, replicates=10000, cluster='project'):
    # Both sides must have known outcomes. Keep pairing even when labels differ
    # across independently generated adaptive attacks.
    pairs = [(a, b) for a, b in pairs if a['y'] in (0, 1) and b['y'] in (0, 1)
             and a['score'] is not None and b['score'] is not None]
    if not pairs:
        return {'name': name, 'paired_n': 0, 'difference': None, 'p': None}
    left, right = zip(*pairs)
    an, ad = metric_vectors(left, metric)
    bn, bd = metric_vectors(right, metric)
    keys = sorted({a[cluster] for a in left})
    inverse = np.array([keys.index(a[cluster]) for a in left])
    matrix = np.stack([np.bincount(inverse, weights=v, minlength=len(keys)) for v in (an, ad, bn, bd)], axis=1)

    def differences(arr):
        return np.divide(arr[:, 0], arr[:, 1], out=np.full(len(arr), np.nan), where=arr[:, 1] > 0) - np.divide(arr[:, 2], arr[:, 3], out=np.full(len(arr), np.nan), where=arr[:, 3] > 0)

    observed = differences(matrix.sum(axis=0)[None, :])[0]
    draws = rng_for(name).multinomial(len(keys), [1/len(keys)]*len(keys), replicates)
    ci = interval(differences(draws@matrix))
    exact = len(keys) <= 14
    swaps = np.array(list(itertools.product((0, 1), repeat=len(keys)))) if exact else rng_for(name+'perm').integers(0, 2, size=(replicates, len(keys)))
    base = matrix.sum(axis=0)
    delta = matrix[:, [2, 3, 0, 1]]-matrix
    perm = differences(base+swaps@delta)
    good = perm[np.isfinite(perm)]
    p = None
    if np.isfinite(observed) and len(good):
        extremes = sum(abs(good) >= abs(observed)-1e-12)
        p = float(extremes/len(good)) if exact else float((extremes+1)/(len(good)+1))
    result = {'name': name, 'paired_n': len(pairs), 'projects': len({a['project'] for a in left}),
            'cluster': cluster, 'clusters': len(keys), 'metric': metric,
            'difference': float(observed) if np.isfinite(observed) else None, 'ci95': ci,
            'p': p, 'permutation': 'exact' if exact else 'Monte Carlo plus one',
            'valid_permutations': len(good),
            'small_project_count': len(keys) < 5}
    if cluster == 'project' and len(keys) < 5:
        result['task_cluster_sensitivity'] = paired_contrast(pairs, metric, name, replicates, 'task_id')
    return result


def bh_adjust(tests):
    order = sorted((i for i, t in enumerate(tests) if t['p'] is not None), key=lambda i: tests[i]['p'])
    running = 1.
    for rank in range(len(order), 0, -1):
        i = order[rank-1]
        running = min(running, tests[i]['p']*len(tests)/rank)
        tests[i]['q_bh'] = running
    for t in tests:
        t.setdefault('q_bh', None)
    return tests


def load_rows(root, overrides=None):
    jobs = json.loads((root/'protocol/formal_jobs.json').read_text())
    tasks = {t['task_id']: t for lang in ('python', 'java') for t in json.loads((root/f'data/{lang}_formal.json').read_text())['tasks']}
    thresholds = json.loads((root/'protocol/thresholds.json').read_text())['thresholds']
    rows = []
    for job in jobs:
        if overrides is not None and job['key'] not in overrides:
            continue
        f = root/'runs/records'/(digest(job['key'])+'.json')
        rec = json.loads(f.read_text()) if f.exists() else {}
        label = (rec.get('reference') or {}).get('y')
        weight = 1
        if overrides is not None:
            label, weight = overrides[job['key']]
        for condition in job['scores']:
            role = condition.split('/')[0]
            rows.append({**{k: v for k, v in job.items() if k != 'scores'}, 'condition': condition,
                         'project': tasks[job['task_id']]['repo'], 'generated': bool(rec.get('review')),
                         'y': label, 'weight': weight, 'threshold': thresholds[role],
                         'score': rec.get('scores', {}).get(condition, {}).get('score')})
    return rows


def grouped_results(rows, replicates):
    groups = defaultdict(list)
    for r in rows:
        if r['language'] == 'Java':
            groups['java/'+(r['strategy'] or 'benign')+'/'+r['condition']].append(r)
        elif r['strategy'] is None:
            groups['rq1/benign/'+r['generator']+'/'+r['condition']].append(r)
        else:
            if r['condition'] == r['target']+'/'+r['defense']:
                groups['adaptive/'+r['target']+'/'+r['defense']+'/'+r['strategy']].append(r)
            if r['paired_panel']:
                groups['fixed_python/'+r['strategy']+'/'+r['condition']].append(r)
    return {name: summarize(group, name, replicates) for name, group in sorted(groups.items())}


def contrasts(rows, replicates):
    families = {}
    for family, subset, models in (
        ('fixed_python', [r for r in rows if r['language'] == 'Python' and (r['strategy'] is None or r['paired_panel'])], ('haiku', 'mini', 'gpt')),
        ('java', [r for r in rows if r['language'] == 'Java'], ('haiku',))):
        matrix = {(r['key'], r['condition']): r for r in subset}
        keys = {r['key'] for r in subset}
        comparisons = [(f'{c}/D5', f'{c}/D1') for c in models]
        comparisons += [(f'{a}/{d}', f'{b}/{d}') for a, b in itertools.combinations(models, 2) for d in ('D1', 'D5')]
        tests = []
        for a, b in comparisons:
            pairs = [(matrix[k, a], matrix[k, b]) for k in keys if (k, a) in matrix and (k, b) in matrix]
            for metric in ('fpr', 'fnr'):
                tests.append(paired_contrast(pairs, metric, family+'/'+a+' minus '+b+'/'+metric, replicates))
        families[family] = bh_adjust(tests)
    subset = [r for r in rows if r['language'] == 'Python' and r['strategy'] and r['condition'] == r['target']+'/'+r['defense']]
    tests = []
    for target in ('haiku', 'gpt'):
        for strategy in ('omission', 'downplay', 'bury'):
            matched = {(r['task_id'], r['repetition'], r['defense']): r for r in subset if r['target'] == target and r['strategy'] == strategy}
            keys = {(t, rep) for t, rep, _ in matched}
            for a, b in itertools.combinations(('D1', 'D4', 'D5'), 2):
                pairs = [(matched[t, rep, a], matched[t, rep, b]) for t, rep in keys if (t, rep, a) in matched and (t, rep, b) in matched]
                tests.append(paired_contrast(pairs, 'joint_harmful_accepted', f'adaptive/{target}/{strategy}/{a} minus {b}', replicates))
    families['adaptive_python'] = bh_adjust(tests)
    return families


def human_results(root, replicates):
    policy_path = root/'protocol/review_policy.json'
    if policy_path.exists() and json.loads(policy_path.read_text())['mode'] == 'official_pro_then_author_review':
        path = root/'author_review/formal/author_labels.json'
        if not path.exists():
            return {'status': 'awaiting_post_experiment_author_check', 'independent_human_reviewers': 0}
        author = json.loads(path.read_text())
        if (author.get('annotator_type') != 'human' or not author.get('review_completed')
                or not author.get('reviewer_id') or not author.get('consent')):
            raise ValueError('author check is incomplete')
        mapping = {r['blind_id']: r for r in json.loads((root/'human/formal/private_mapping.json').read_text())}
        values = {r['blind_id']: parse_reference(json.dumps(r)) for r in author['records']
                  if r.get('checked') and r['blind_id'] in mapping}
        overrides = {mapping[b]['key']: (v['y'], 1) for b, v in values.items()}
        return {'status': 'post_experiment_author_check', 'checked': len(values),
                'offered': len(mapping), 'independent_human_reviewers': 0,
                'groups': grouped_results(load_rows(root, overrides), replicates),
                'note': 'Descriptive results on actually checked items. Post hoc coverage may be selective; no population-weighted or two-human-reviewer claim.'}
    folder = root/'human/formal'
    files = [folder/f'reviewer_{i}.json' for i in (1, 2)]
    if not all(f.exists() for f in files):
        return {'status': 'awaiting_two_independent_human_reviewers'}
    people = [json.loads(f.read_text()) for f in files]
    if (any(not p.get('consent') or not p.get('experience') or not p.get('independent_annotation') for p in people)
            or not people[0].get('reviewer_id') or people[0]['reviewer_id'] == people[1].get('reviewer_id')):
        raise ValueError('invalid human metadata')
    mapping = {r['blind_id']: r for r in json.loads((folder/'private_mapping.json').read_text())}
    labels = []
    results = {}
    for i, person in enumerate(people, 1):
        values = {r['blind_id']: parse_reference(json.dumps(r)) for r in person['records'] if r['blind_id'] in mapping}
        labels.append(values)
        overrides = {mapping[b]['key']: (v['y'], 1/mapping[b]['inclusion_probability']) for b, v in values.items()}
        results[f'reviewer_{i}'] = {'annotated': len(values), 'groups': grouped_results(load_rows(root, overrides), replicates)}
    common = sorted(set(labels[0]) & set(labels[1]))
    agreement = {}
    for dimension in ('C', 'A', 'M', 'y'):
        pairs = [(labels[0][k][dimension], labels[1][k][dimension]) for k in common]
        pairs = [(a, b) for a, b in pairs if a in (0, 1) and b in (0, 1)]
        n = len(pairs)
        observed = sum(a == b for a, b in pairs)/n if n else None
        expected = sum((sum(a == c for a, _ in pairs)/n)*(sum(b == c for _, b in pairs)/n) for c in (0, 1)) if n else None
        agreement[dimension] = {'known_pairs': n, 'unresolved_pairs': len(common)-n, 'agreement': observed,
                                'cohen_kappa': (observed-expected)/(1-expected) if n and expected < 1 else None}
    return {'status': 'independent_annotations_analyzed', 'agreement': agreement, 'results': results,
            'note': 'Inverse-inclusion weighted metrics; each reviewer analyzed separately before adjudication. No synthetic human labels.'}


def machine_results(root, replicates):
    path = root/'machine_review/formal/results.json'
    if not path.exists():
        return {'status': 'awaiting_official_pro_audit'}
    audit = json.loads(path.read_text())
    if audit.get('annotator_type') != 'model':
        raise ValueError('machine audit provenance mismatch')
    results, labels = {}, []
    for rep in (1, 2):
        annotations = [a for a in audit['annotations'] if a['pass'] == rep]
        values = {a['key']: parse_reference(json.dumps(a['label'])) for a in annotations if a.get('label')}
        labels.append(values)
        overrides = {a['key']: ((values.get(a['key']) or {}).get('y'), 1/a['inclusion_probability']) for a in annotations}
        results[f'pass_{rep}'] = {'requested': len(annotations), 'parsed': len(values),
                                'groups': grouped_results(load_rows(root, overrides), replicates)}
    common = sorted(set(labels[0]) & set(labels[1]))
    agreement = {}
    for dimension in ('C', 'A', 'M', 'y'):
        pairs = [(labels[0][k][dimension], labels[1][k][dimension]) for k in common]
        known = [(a, b) for a, b in pairs if a in (0, 1) and b in (0, 1)]
        agreement[dimension] = {'known_pairs': len(known), 'unknown_pairs': len(pairs)-len(known),
                                'same_label_fraction': ratio(sum(a == b for a, b in known), len(known))}
    return {'status': audit['status'], 'annotator_type': 'model', 'results': results,
            'repeated_request_agreement': agreement, 'disagreements_with_flash_or_unknown': audit['disagreements_or_unknown'],
            'note': 'Two requests to the same official Pro model; not independent human reviewers. Pro and Flash share a model family. No automatic adjudication or retuning from formal labels.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    root = Path(args.root)
    complete = (root/'runs/formal_calls_finished.json').exists()
    if not complete and not args.allow_partial:
        raise RuntimeError('formal calls not finished; use explicit partial mode for diagnostics')
    plan = json.loads((root/'protocol/statistics.json').read_text())
    replicates = plan['uncertainty']['bootstrap_replicates']
    rows = load_rows(root)
    out = {'formal_call_processing_complete': complete, 'statistics_sha256': digest(plan),
           'automatic_reference': {'groups': grouped_results(rows, replicates), 'paired_tests': contrasts(rows, replicates)},
           'official_pro_audit': machine_results(root, replicates),
           'human': human_results(root, replicates)}
    dump(root/'analysis'/('results.json' if complete else 'partial_results.json'), out)


if __name__ == '__main__':
    main()
