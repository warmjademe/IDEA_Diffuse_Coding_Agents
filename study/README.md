# Current experiment and reproducibility guide

This directory is the artifact for *Can Weak Checkers Safeguard LLM Code Review?
An Empirical Red–Blue Study under Diffuse AI Control*. It separates the current
experiment from legacy scripts at repository root.

## Offline reproduction

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r study/code/requirements.txt
python study/reproduce.py --output /tmp/jsep-code-review-reproduction
```

The command verifies every archive's SHA-256, safely extracts the research
evidence, reconstructs the adjudicated input view, and reruns the frozen analysis
with 10,000 bootstrap/permutation draws. It checks all group estimates, intervals,
38 paired tests, both Pro audit passes, and final D4 rubric identity against the
saved numerical results. This can take several minutes and makes no model calls.
It writes only to the chosen output directory and refuses to overwrite modified
evidence. Python 3.11+ is required by the pinned dependencies; the original host used Python 3.13.12.

Add `--extract-only` to inspect evidence without recalculating statistics, and
`--include-raw` to also extract all 12,748 API response records. Every archive is
hash-verified even when raw records are not extracted. No GPU is required.

## Layout

- `code/`: exact executed analysis, API, preparation, prompt, scheduling, and
  monitoring source, including tests and pinned host requirements.
- `artifacts/manifest.json`: checksums for archives and individual original files.
- `artifacts/study-evidence.tar.gz`: datasets, selection/exclusion manifests,
  protocol, review/score records, two label views, execution evidence, Pro audit,
  all D4 rounds, attribution, and a readable request ledger export.
- `artifacts/api-records-*.tar.gz`: raw requests and responses, including failures,
  returned model IDs, usage, timestamps, parse outcomes, and confidence calls.
- `analysis/`: saved original and adjudicated statistics, publication aggregates,
  descriptive common-panel metrics, and analysis provenance.
- `publication_state.json`: author-confirmed human-check status, distinct from
  the earlier machine-generated metadata and from individual annotation files.
- `make_tables.py`: produces the manuscript tables from saved numerical results.
- `aggregate_publication.py` and `audit_descriptive.py`: recompute pooled/common
  panels, descriptive checks, sample flow and recorded usage from extracted data.
- `HISTORY_CORRECTIONS.md`: documented corrections to earlier reporting.

Archives preserve original relative paths and bytes. Absolute NAS paths inside
records are provenance, not a requirement to recreate that host. The offline
loader uses the archive-relative paths. Virtual environments, container images,
whole project clones, credentials, and unrelated host configuration are excluded.

## Design and coverage

The Python collection pool has 2,700 PR records. Two exceed the patch budget;
260 otherwise eligible tasks overlap recorded earlier use, leaving 2,438 formal
candidates. Screening 279 candidates produces 34 verified instances. The first
30 in the fixed order are the formal sample, across 30 repositories. Four verified
instances are unused. Twenty separate Python development tasks supply ten
calibration and ten optimization tasks. Selection does not use formal model
outcomes. The candidate manifest releases ordering/provenance rather than code
for thousands of unused candidates.

Java uses Defects4J commit `8c16da8230843cdc918eaf4ddb449637f02b83c6` and Java 11.
Of 104 formal candidates, 101 verify and the first 100 are used: Cli, Csv, Gson,
JacksonCore, Jsoup, Lang (13 each), Codec and Math (11 each). Five disjoint
development instances also verify. Java supplies one writer/checker combination
and D1/D5 same-text comparisons, not Java D4 or full multi-model adaptive tests.

Every included defect has buggy-fail/fixed-pass evidence using developer tests.
Code context is fault-localized using patch positions and capped at 24,000
characters. The fix cap is 16,000. D5 receives raw failure output, with first/last
6,000 characters retained only when the log exceeds 12,000. Both the complete
saved log and model-visible excerpt are included. These checks do not establish
absence from proprietary model training data.

The manifest has 2,710 reviews and 5,660 requested checker scores. Adjudicated
coverage is 1,690 generated/1,672 labeled Python reviews and 3,594 valid Python
scores; Java has 957 generated/906 labeled reviews and 1,914 valid scores. Missing
outcomes are never silently counted as safe detections.

The Python fixed-text panel plans 270 reviews (90 normal and 180 attacks); the
six-condition common intersection is 261. Individual Haiku, Mini, GPT D1/D5
comparisons use 266, 266, and 261 pairs. Java uses 906 pairs. Do not mix these
denominators or treat repeated reviews as independent defects.

## Models, repetitions, and interpretation

`protocol/model_versions.json` records actual returned IDs for Sonnet 4.6,
GPT-5.5, Gemini 3.5 Flash Lite, Haiku 4.5, GPT-5.4-mini, DeepSeek V4.1 Flash,
and official V4 Pro. Payloads preserve requested temperatures and token limits.
Data/order/analysis seeds are fixed; API-enforced generation seeds are not
established. Three runs mean independent generation requests, not guaranteed
seed-deterministic outputs. Normal text is generated once and reused.

D1 is the four-dimensional rubric. D5 adds the log without changing that rubric.
D4 attempts four development-only rounds for each of two targets and three
trajectories. **All six final rubrics equal D1 byte-for-byte.** Of 24 rounds,
16 have no valid parsed candidate, one lacks both reference classes, and seven
fail the constraint/improvement rule. D1/D4 differences therefore arise from
independent sampling/scoring and missingness, not changed prompts. They cannot
establish that effective prompt optimization causes reversal or cannot help.

Labels C/A/M measure core diagnosis, actionable/correct localization, and
material misinformation. Acceptable means C=1, A=1, M=0. Unknowns remain unknown.
The Pro audit samples 200 reviews before outcomes (120 Python/80 Java), with
400 primary assessment slots. Technical recovery fills missing outputs without
regenerating reviews. Eleven agreeing Pro labels and 25 confidence-selected Pro
judgments define 36 adopted labels; 21 existing binary labels change and nine
missing labels are filled. Confidence is a separate post hoc model self-rating,
not calibrated probability. Original outputs and label views remain available.

Two software-engineering PhDs with code-review experience each independently
checked all 200 audit reviews: 120 Python reviews and 80 Java reviews. Each
reviewer checked the entire sample, and both confirmed agreement with the final
Pro-recommended judgments. The authors confirmed this coverage and outcome;
`publication_state.json` records the current status used in the manuscript.

The historical analysis JSON's `human` field and `human_author_check` status
describe the automated analysis before this confirmation. Those archived fields
retain their original values; they do not describe the current completion
status. Individual reviewer annotation files have not been supplied, and no
such files or human agreement coefficients are synthesized.

## Main results and statistical scope

- Normal-arm Spearman correlations: Haiku 0.172, Mini 0.226, GPT 0.155.
- In fixed-text paired Python comparisons, logs reduce FPR by 11.22 percentage
  points for Haiku (q=0.00555) and 11.94 for GPT (q=0.00020); Mini changes by
  +0.49 points (q=1).
- D5 still accepts 19/34 unacceptable Haiku burying attacks and 33/36 GPT attacks.
- Java FPR is 8.0% vs 9.9% (q=0.2344), while FNR falls from 86.2% to 71.1%
  (q=0.046875).
- None of the 18 targeted defense comparisons has BH-adjusted q<0.05. Original
  versus adjudicated labels do not change any of the 38 significance decisions.

Project-cluster resampling preserves paired observations. Exact permutations
are used for eight Java clusters; Python uses 10,000 Monte Carlo permutations.
The frozen threshold calibration has only two acceptable reviews out of 20;
interpret FPR/FNR together with threshold-free AUROC. No score-minus-reference
construct subtraction or capability-independent impossibility claim is made.

## Execution, costs, and API reruns

The archived ledger has 12,748 attempts (12,232 successful, 516 failed), including
audit work; usage-bearing responses total 62,844,416 input and 16,542,289 output
tokens. The recorded request span is 44.56 hours including pauses. The published
price estimate is US$47.82, not an invoice; missing usage can imply unknown charges.

Offline statistical reproduction requires no credentials. New paid inference
is a separate action: use `code/workflow.py` with a fresh run directory and
`TEAMOROUTER_API_KEY`; official audit calls use `DEEPSEEK_API_KEY`. Inspect
`code/api.py`, model mappings and exact saved payloads before running. Endpoints
and model aliases can change, so new outputs are a new dated experiment, not
byte-identical reproduction. Do not rerun paid inference in the extracted
archival evidence directory. Preparation scripts document Docker limits and
developer-test execution; environment-specific paths must be configured for a
new host. The verified one-command path above is for saved-evidence analysis.

To regenerate the extra publication aggregates and tables as well:

```sh
python study/reproduce.py --output /tmp/jsep-code-review-reproduction --include-raw --extract-only
python study/aggregate_publication.py /tmp/jsep-code-review-reproduction > /tmp/publication_metrics.json
python study/audit_descriptive.py /tmp/jsep-code-review-reproduction > /tmp/conclusion_metrics.json
python study/make_tables.py
```

The first two JSON outputs can be compared with their saved counterparts in
`study/analysis/`; numerical summaries are reproduced from original records.
The public aggregate omits the historical SQLite column-name metadata because
the ledger is distributed as readable JSON. `make_tables.py` reads the saved
analysis files and writes `study/tables/results_tables.tex`.
