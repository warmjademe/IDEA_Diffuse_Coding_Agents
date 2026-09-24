"""Offline publication audit; never calls a model or mutates experiment inputs."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib
import json
import sqlite3
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'code'))
import analyze

def read(path):
    return json.loads(path.read_text())

view = root / 'supplement/20260924_audit_gaps/analysis_view_adopted_pro'
rows = analyze.load_rows(view)
out = {'source_sha256': hashlib.sha256((view/'analysis/results.json').read_bytes()).hexdigest()}
pc = read(root/'data/python_candidate_manifest.json')
out['python_flow'] = {
    'corpus': pc['corpus_n'], 'eligible': len(pc['tasks']),
    'pre_exclusions': dict(Counter(x['reason'] for x in pc['pre_execution_exclusions'])),
    'historically_seen_in_eligible': len(set(pc['tasks']) & set(pc['historical_ids'])),
    'formal_candidates': len(pc['formal_order'])}
attempts = read(root/'data/pre_30_amendment/python_formal_progress.json')['attempts']
out['python_flow']['formal_screening'] = {
    'attempts': len(attempts), 'statuses': dict(Counter(x['status'] for x in attempts)),
    'failure_reasons': dict(Counter(x.get('reason','') for x in attempts if x['status'] != 'verified'))}
for language in ('python','java'):
    for split in ('development','formal'):
        d = read(root/f'data/{language}_{split}.json')
        ts = d['tasks']
        out[f'{language}_{split}'] = {
            'tasks': len(ts), 'projects': dict(Counter(t['repo'] for t in ts)),
            'log_truncated': sum(t['log_truncated'] for t in ts),
            'max_code_chars': max(len(t['code_context']) for t in ts),
            'max_patch_chars': max(len(t['gold_patch']) for t in ts),
            'earliest_merge': min((t.get('merged_at','') for t in ts),default=''),
            'latest_merge': max((t.get('merged_at','') for t in ts),default='')}
        if 'attempts' in d:
            out[f'{language}_{split}']['screening'] = {
                'attempts': len(d['attempts']),
                'statuses': dict(Counter(x['status'] for x in d['attempts'])),
                'failure_reasons': dict(Counter(x.get('reason','') for x in d['attempts'] if x['status'] != 'verified'))}
out['optimization'] = defaultdict(list)
for f in sorted((root/'runs/optimization').rglob('*.json')):
    d=read(f)
    out['optimization'][f.parent.name].append({'file': str(f.relative_to(root)),
        'accepted': d['accepted'], 'reason': d['reason'],
        'current_rates': d['current_rates'], 'candidate_rates': d['candidate_rates']})
jobs=read(root/'protocol/formal_jobs.json')
out['coverage']={}
for language in ('Python','Java'):
    js=[j for j in jobs if j['language']==language]
    records=[read(view/'runs/records'/(analyze.digest(j['key'])+'.json')) for j in js]
    relevant=[r for r in rows if r['language']==language]
    out['coverage'][language]={'requested':len(js),'generated':sum(bool(r.get('review')) for r in records),
        'labeled':sum((r.get('reference') or {}).get('y') in (0,1) for r in records),
        'reference_y':dict(Counter(str((r.get('reference') or {}).get('y')) for r in records)),
        'requested_scores':len(relevant),'valid_scores':sum(r['score'] is not None for r in relevant)}
out['summaries']={}
normal=[r for r in rows if r['language']=='Python' and r['strategy'] is None]
for checker in ('haiku','mini','gpt'):
    group=[r for r in normal if r['condition']==checker+'/D1']
    out['summaries']['normal/'+checker]=analyze.summarize(group,'publication/normal/'+checker)
fixed=[r for r in rows if r['language']=='Python' and (r['strategy'] is None or r['paired_panel'])]
matrix={(r['key'],r['condition']):r for r in fixed}
conditions=[f'{c}/{d}' for c in ('haiku','mini','gpt') for d in ('D1','D5')]
keys=sorted({r['key'] for r in fixed})
common=[k for k in keys if all((k,c) in matrix and matrix[k,c]['y'] in (0,1) and matrix[k,c]['score'] is not None for c in conditions)]
for c in conditions:
    out['summaries']['common/'+c]=analyze.summarize([matrix[k,c] for k in common],'publication/common/'+c)
out['ledger']={}
ledger=read(root/'runs/ledger_export.json')
out['ledger']['time_range']=[min(r['started'] for r in ledger),max(r['ended'] for r in ledger if r['ended'] is not None),len(ledger)]
out['ledger']['status_counts']=[
    [status,sum(r['status']==status for r in ledger),
     sum(r['estimated_usd'] or 0 for r in ledger if r['status']==status)]
    for status in sorted({r['status'] for r in ledger})]
assert (root/'runs/raw').is_dir(), 'Extract with --include-raw for complete usage verification'
raw_usage=Counter()
for f in (root/'runs/raw').glob('*.json'):
    d=read(f)
    usage=(d.get('raw_response') or {}).get('usage') or {}
    for k in ('prompt_tokens','completion_tokens','total_tokens'):
        raw_usage[k] += usage.get(k,0) or 0
    raw_usage['artifacts_with_usage'] += bool(usage)
out['raw_usage']=dict(raw_usage)
print(json.dumps(out,ensure_ascii=False,indent=2))
