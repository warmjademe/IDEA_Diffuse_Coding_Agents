# Can Weak Checkers Safeguard LLM Code Review?

The current research artifact is in **[study/](study/README.md)**. It contains
the September 2026 experiment on **30 Python and 100 Java defects**, its frozen
implementation, prompts, task manifests, test evidence, raw model records,
reference-label provenance, statistics, and an offline reproduction command.

The study compares review scoring without and with regression-test failure
output, three checkers, and omission, downplaying, and burying attacks. Main
inference uses TeamRouter; the reference audit uses the official DeepSeek Pro
endpoint. Reproducing the saved statistics makes **no API calls**.

Two software-engineering PhDs with code-review experience each independently
checked all 200 audit reviews (120 Python and 80 Java), and their checks agreed
with the final Pro-recommended judgments. The author-confirmed completion and
coverage are recorded in [publication_state.json](study/publication_state.json).

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r study/code/requirements.txt
python study/reproduce.py --output /tmp/jsep-code-review-reproduction
```

Use Python 3.11 or newer (the recorded environment used 3.13.12). See the study
README for exact coverage, missing outcomes, seeds, model versions, and costs.

The principal findings are conditional: logs improve Python ranking and reduce
false acceptance for two checkers, but attacks that name the defect can still
evade them. Java mainly shows reduced false rejection. **No D4 rubric update
was accepted in any of the six trajectories**; all final rubrics equal D1.
The artifact does not treat that failed update procedure as evidence about the
effect of successfully changed rubrics.

Earlier root-level scripts, `EXPERIMENTS.md`, and `STATE.md` are retained as legacy
development material. Their sample descriptions and exploratory RQ numbering
are not the current experiment. [HISTORY_CORRECTIONS.md](study/HISTORY_CORRECTIONS.md)
documents the discrepancies found in the earlier manuscript/records.

Credentials are not included. Third-party source excerpts and test material
retain their upstream rights; see [THIRD_PARTY.md](study/THIRD_PARTY.md).
