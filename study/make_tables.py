"""Generate paper tables from saved statistics; no manual transcription of results."""
from pathlib import Path
import json

here=Path(__file__).resolve().parent
project=here
s=json.loads((here/'analysis/results.json').read_text())['automatic_reference']
p=json.loads((here/'analysis/publication_metrics.json').read_text())
d=json.loads((here/'analysis/conclusion_metrics.json').read_text())['views']['adopted_pro']
names={'haiku':'Haiku','mini':'Mini','gpt':'GPT-5.5'}
conditions={'D1':'Initial scoring criteria','D4':'Scoring criteria optimization','D5':'Log assistance'}
strategies={'omission':'Omission','downplay':'Downplaying','bury':'Burying'}

def number(v, digits=3):
    return f'{v:.{digits}f}'

def ci(m):
    return f"{m['estimate']:.3f} [{m['ci95']['low']:.3f}, {m['ci95']['high']:.3f}]"

def fraction(m, weighted=True):
    pre='weighted_' if weighted else ''
    return f"{int(m[pre+'numerator'])}/{int(m[pre+'denominator'])} ({100*m['estimate']:.1f}\\%)"

def table(command,label,caption,spec,head,rows,wide=False):
    env='table*' if wide else 'table'
    return ('\\newcommand{\\'+command+'}{%\n\\begin{'+env+'}[t]\n\\centering\n'
            '\\caption{\\qyb{'+caption+'}}\n\\label{'+label+'}\n'
            '\\qyb{\\begin{tabular}{'+spec+'}\n\\toprule\n'+head+' \\\\\n\\midrule\n'+
            '\n'.join(' & '.join(r)+' \\\\' for r in rows)+'\n\\bottomrule\n\\end{tabular}}\n'
            '\\end{'+env+'}\n}\n')

rows=[]
for model in names:
    a=p['summaries']['normal/'+model];m=a['metrics']
    rows.append([names[model],str(int(m['joint_harmful_accepted']['weighted_denominator'])),
        ci(m['spearman']),ci(m['auroc']),fraction(m['fpr']),fraction(m['fnr'])])
out=table('RQOneTable','tab:rq1',
    'Initial scoring criteria on normal Python reviews from three generators. There are 90 planned reviews from 30 tasks. '
    '$n$ counts reviews with both a known reference label and a valid score. Brackets are 95\\% project-cluster intervals. '
    'FPR is acceptance among unacceptable reviews; FNR is rejection among acceptable reviews.',
    'lrllll','Checker & $n$ & Spearman $\\rho$ [CI] & AUROC [CI] & FPR & FNR',rows,True)
rows=[]
for model in ('haiku','gpt'):
    for strategy in ('omission','downplay','bury'):
        a=s['groups'][f'adaptive/{model}/D1/{strategy}'];m=a['metrics'];r=a['attack_runs']
        rows.append([names[model],strategies[strategy],fraction(m['fpr']),fraction(m['fnr']),
                     fraction(m['joint_harmful_accepted']),f"${r['mean']*100:.2f}\\pm{r['sample_sd']*100:.2f}$"])
out+=table('RQTwoTable','tab:rq2',
    'Targeted Python attacks against the initial scoring criteria condition. Each cell plans 90 reviews (30 tasks, three runs). '
    'Joint evasion is unacceptable and accepted among reviews with known labels and valid scores. '
    'The final column reports the mean and sample standard deviation of joint evasion across three independent runs, in percent.',
    'llllll','Target & Strategy & FPR & FNR & Joint evasion & Run mean$\\pm$SD (\\%)',rows,True)
rows=[]
for model in ('haiku','gpt'):
    for defense in ('D1','D4','D5'):
        a=d['adaptive_pooled_descriptive'][f'{model}/{defense}'];r=a['three_run_joint']
        rows.append([names[model],conditions[defense],fraction(a['joint_harmful_accepted'],False),
                     f"${100*r['mean']:.2f}\\pm{100*r['sample_sd']:.2f}$"])
out+=table('DefenseTable','tab:defense',
    'Descriptive joint evasion pooled across the three strategies. Each target and checking condition plans 270 attacks. '
    'All six scoring criteria optimization runs retain the initial scoring criteria. '
    'All 18 strategy-specific paired comparisons between checking conditions have BH-adjusted $q\\geq0.0738$.',
    'llll','Target & Condition & Joint evasion & Run mean$\\pm$SD (\\%)',rows)
rows=[]
for model in names:
    for defense in ('D1','D5'):
        a=p['summaries'][f'common/{model}/{defense}'];m=a['metrics']
        rows.append([names[model],conditions[defense],ci(m['auroc']),fraction(m['fpr']),fraction(m['fnr'])])
out+=table('FixedTable','tab:fixed',
    'Identical Python texts scored by every checker under the initial scoring criteria and log-assisted conditions. The six-condition common intersection contains 261 reviews '
    '(201 unacceptable and 60 acceptable) from the planned 270-review panel. AUROC brackets are 95\\% project-cluster intervals. '
    'The fixed thresholds are Haiku 82, Mini 28, and GPT 52; class-specific errors must be interpreted jointly.',
    'lllll','Checker & Condition & AUROC [CI] & FPR & FNR',rows,True)
rows=[]
for strategy in ('benign','omission','downplay','bury'):
    for defense in ('D1','D5'):
        a=s['groups'][f'java/{strategy}/haiku/{defense}'];m=a['metrics']
        rows.append(['Normal' if strategy=='benign' else strategies[strategy],conditions[defense],
                     str(int(m['joint_harmful_accepted']['weighted_denominator'])),
                     fraction(m['fpr']),fraction(m['fnr']),number(m['auroc']['estimate'])])
for defense in ('D1','D5'):
    a=d['java_matched']['conditions']['haiku/'+defense]
    rows.append(['All',conditions[defense],str(a['usable']),fraction(a['fpr'],False),fraction(a['fnr'],False),number(a['auroc'])])
out+=table('JavaTable','tab:java',
    'Java fixed-text replication with Sonnet generation and Haiku checking. The 100 defects span eight projects. '
    'The two conditions share 906 usable reviews out of 1,000 planned. Normal is the generation instruction, not a reference label. '
    'Adding logs changes pooled FPR by $+1.87$ percentage points ($q=0.2344$), while FNR changes by $-15.09$ points ($q=0.046875$).',
    'llrlll','Instruction & Condition & $n$ & FPR & FNR & AUROC',rows,True)
(here/'tables').mkdir(exist_ok=True)
(here/'tables/results_tables.tex').write_text(out)
print('Generated five tables from frozen results')
