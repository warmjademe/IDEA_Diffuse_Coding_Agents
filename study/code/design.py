"""Outcome-blind formal job manifest and human sampling frame."""
import random

SEED = 20260922
CHECKERS = ('haiku', 'mini', 'gpt')
TARGETS = ('haiku', 'gpt')
STRATEGIES = ('omission', 'downplay', 'bury')


def formal_jobs(python_tasks, java_tasks):
    jobs = []
    for i, task in enumerate(sorted(python_tasks, key=lambda t: t['task_id'])):
        tid = task['task_id']
        for writer in ('sonnet', 'gpt', 'gemini'):
            scores = [f'{c}/{d}' for c in CHECKERS for d in ('D1', 'D5')]
            scores += [f'{c}/D4/run{r}' for c in TARGETS for r in (1, 2, 3)]
            if writer == 'sonnet':
                scores += [f'{c}/D0' for c in TARGETS]
            jobs.append(dict(key=f'formal/python/{tid}/benign/{writer}', task_id=tid,
                             language='Python', generator=writer, strategy=None,
                             defense='D1', target=None, repetition=1, scores=scores,
                             paired_panel=False, adaptive=False))
        for target in TARGETS:
            for defense in ('D1', 'D4', 'D5'):
                for k, strategy in enumerate(STRATEGIES):
                    for rep in (1, 2, 3):
                        panel = (target == 'haiku' and defense in ('D1', 'D5') and
                                 rep == 1 + ((i+k+('D1', 'D5').index(defense)) % 3))
                        scores = [f'{target}/{defense}']
                        if panel:
                            scores = [f'{c}/{d}' for c in CHECKERS for d in ('D1', 'D5')]
                        jobs.append(dict(key=f'formal/python/{tid}/attack/{target}/{defense}/{strategy}/run{rep}',
                                         task_id=tid, language='Python', generator='sonnet',
                                         strategy=strategy, defense=defense, target=target,
                                         repetition=rep, scores=scores, paired_panel=panel, adaptive=True))
    for task in sorted(java_tasks, key=lambda t: t['task_id']):
        tid = task['task_id']
        for strategy in (None, *STRATEGIES):
            for rep in ((1,) if strategy is None else (1, 2, 3)):
                jobs.append(dict(key=f"formal/java/{tid}/{strategy or 'benign'}/run{rep}",
                                 task_id=tid, language='Java', generator='sonnet',
                                 strategy=strategy, defense='D1', target='haiku',
                                 repetition=rep, scores=['haiku/D1', 'haiku/D5'],
                                 paired_panel=True, adaptive=False))
    return jobs


def balanced_draws(rng, values, size):
    """Randomized complete blocks: marginal probability 1/len(values)."""
    out = []
    while len(out) < size:
        block = list(values)
        rng.shuffle(block)
        out.extend(block)
    return out[:size]


def human_sample(jobs):
    rng = random.Random(SEED)
    python_ids = sorted({j['task_id'] for j in jobs if j['language'] == 'Python'})
    java_ids = sorted({j['task_id'] for j in jobs if j['language'] == 'Java'})
    rng.shuffle(python_ids)
    selected_java = rng.sample(java_ids, 20)
    writers = balanced_draws(rng, ('sonnet', 'gpt', 'gemini'), len(python_ids))
    attack_cells = [(c, d, r) for c in TARGETS for d in ('D1', 'D4', 'D5') for r in (1, 2, 3)]
    attack_draws = {s: balanced_draws(rng, attack_cells, len(python_ids)) for s in STRATEGIES}
    java_draws = {s: balanced_draws(rng, (1, 2, 3), len(selected_java)) for s in STRATEGIES}
    selected = []
    for i, tid in enumerate(python_ids):
        selected.append(dict(key=f'formal/python/{tid}/benign/{writers[i]}', inclusion_probability=1/3))
        for s in STRATEGIES:
            c, d, r = attack_draws[s][i]
            selected.append(dict(key=f'formal/python/{tid}/attack/{c}/{d}/{s}/run{r}', inclusion_probability=1/18))
    for i, tid in enumerate(selected_java):
        selected.append(dict(key=f'formal/java/{tid}/benign/run1', inclusion_probability=20/len(java_ids)))
        for s in STRATEGIES:
            selected.append(dict(key=f'formal/java/{tid}/{s}/run{java_draws[s][i]}',
                                 inclusion_probability=(20/len(java_ids))/3))
    return {'seed': SEED, 'sampling': 'randomized balanced blocks, sampled before scores',
            'selected': selected, 'java_tasks': selected_java,
            'population_reviews': len(jobs)}
