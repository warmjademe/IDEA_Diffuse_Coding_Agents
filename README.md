# Can Weak Checkers Safeguard LLM Code Review?

Code and data for **Can Weak Checkers Safeguard LLM Code Review? An Empirical
Red–Blue Study under Diffuse AI Control**.

The study asks whether a model checker can identify reviews that deliberately
omit a defect or mislead its repair, and whether changing the scoring criteria
or adding test-failure logs improves its judgments. The current experiment,
conducted in September 2026, covers **30 Python defects from 30 repositories**
and **100 Java defects from eight Defects4J projects**.

**Start with [the study guide](study/README.md).** The [study directory](study/)
contains the experiment implementation, prompts, task manifests, regression-test
evidence, model inputs and outputs, reference labels, and statistical results.
The numerical evidence was published in commit
[`88319fd`](https://github.com/warmjademe/IDEA_Diffuse_Coding_Agents/commit/88319fd);
subsequent documentation and presentation changes describe the same experiment.

## Research questions and experimental coverage

| Research question | Evaluation |
|---|---|
| RQ1: Do checker scores reflect review acceptability? | Normally generated Python reviews, assessed by Haiku, Mini, and GPT-5.5. |
| RQ2: Can misleading reviews evade checking? | Omission, downplaying, and burying attacks against Haiku and GPT-5.5, with three independent generations per strategy and task. |
| RQ3: How do scoring criteria optimization and failure evidence affect checking? | Fixed-text comparisons across three Python checkers, targeted attacks against checking conditions, and a Java comparison with Sonnet generation and Haiku checking. |

The checking conditions are **Initial scoring criteria**, **Scoring criteria
optimization**, and **Log assistance**. An additional overall-scoring control
examines normal reviews without dimension-level scoring.

Sonnet, GPT-5.5, and Gemini generate normal Python reviews; Sonnet generates all
attacks. DeepSeek V4.1 Flash provides primary reference assessments supported by
hidden fixes and test evidence. DeepSeek V4 Pro assesses 200 audit reviews twice.
Two software-engineering PhDs with code-review experience each independently
checked all 200 reviews (120 Python and 80 Java) and confirmed agreement with the
final Pro-recommended judgments. See [publication_state.json](study/publication_state.json).

## Main findings

- Normal-review scores have weak associations with acceptability: Spearman
  correlations are 0.172 for Haiku, 0.226 for Mini, and 0.155 for GPT-5.5.
- For identical Python review texts, failure logs reduce false acceptance by
  11.22 percentage points for Haiku and 11.94 for GPT-5.5; Mini has no decrease.
- In Java, logs reduce Haiku's rejection of acceptable reviews from 86.2% to
  71.1%, while acceptance of unacceptable reviews changes from 8.0% to 9.9%.
- Against log-assisted checkers, burying attacks still lead to acceptance of
  19/34 unacceptable reviews by Haiku and 33/36 by GPT-5.5.
- All six scoring criteria optimization runs retain the initial scoring
  criteria. No candidate satisfies the adoption requirements.

The [study guide](study/README.md#results-and-statistical-scope) gives comparison
denominators, statistical tests, and missing-outcome handling.

## Reproduce the saved results

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r study/code/requirements.txt
python study/reproduce.py --output /tmp/jsep-code-review-reproduction
```

Use Python 3.11 or newer; the recorded environment used Python 3.13.12.
This command verifies archive hashes and recomputes the saved statistics without
model API calls or a GPU. Add `--include-raw` to extract raw request/response
records, or `--extract-only` to inspect evidence without statistical recomputation.

## Repository contents

| Location | Contents |
|---|---|
| [study/code/](study/code/) | Frozen experiment implementation, prompts, and offline tests. |
| [study/artifacts/](study/artifacts/) | Six checksummed archives containing task data, execution evidence, and model records. |
| [study/analysis/](study/analysis/) | Original and verified-label analyses, publication summaries, and sensitivity checks. |
| [study/reproduce.py](study/reproduce.py) | Offline verification and statistical reproduction entry point. |
| [study/make_tables.py](study/make_tables.py) | Five result-table exports using the manuscript's condition and strategy names. |
| [study/RECORD_FORMAT.md](study/RECORD_FORMAT.md) | Mapping between manuscript terminology and archived record fields. |

The superseded root-level prototype scripts and progress notes have been removed
from the current branch. They remain available in
[Git history](https://github.com/warmjademe/IDEA_Diffuse_Coding_Agents/tree/0c1f0bd).
[Historical reporting corrections](study/HISTORY_CORRECTIONS.md) remain documented.

Credentials are not included. Third-party source excerpts and test material
retain their upstream rights; see [THIRD_PARTY.md](study/THIRD_PARTY.md).
