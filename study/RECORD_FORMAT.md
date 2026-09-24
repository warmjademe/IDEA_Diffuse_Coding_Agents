# Archived records and manuscript terminology

The manuscript and documentation use descriptive names. The frozen experiment
code and JSON records retain the identifiers used when the experiment ran.

| Archived key | Manuscript term | Meaning |
|---|---|---|
| `D0` | Overall-scoring control | A single overall score for the normal Sonnet-review subset. |
| `D1` | Initial scoring criteria | Initial structured scoring criteria, without failure logs. |
| `D4` | Scoring criteria optimization | Scoring criteria retained after the development procedure, without logs. All six runs retain the initial criteria. |
| `D5` | Log assistance | Initial scoring criteria with model-visible failure logs. |
| `omission` | Omission | Withhold the target defect and useful diagnostic information. |
| `downplay` | Downplaying | Report the defect while understating its consequences or repair priority. |
| `bury` | Burying | Report the defect alongside fabricated problems or misleading priorities. |
| `benign` | Normal generation | Generation instruction; acceptability is determined separately from reference labels. |

These identifiers are record keys, not an ordered list of defenses. Renaming
them in original records would change the archived evidence and break existing
joins and checksum verification. `make_tables.py` translates them for display.

## Effective protocol

Extract the data with `reproduce.py --extract-only`. The resulting
`protocol/statistics.json` is the amended, executed statistical protocol for
the 30-Python/100-Java study. It defines the 200-review audit and comparison
families. `protocol/thresholds.json`, `protocol/model_versions.json`, and
`protocol/model_parameters.json` record the selected thresholds and model settings.

`code/statistics.json` is an earlier development template preserved with the
frozen source snapshot. It is not the effective configuration for the published
results; do not use it in place of `protocol/statistics.json`. The reproduction
command reconstructs the analysis using the archived effective protocol.

The final reference-label view is stored under
`supplement/20260924_audit_gaps/analysis_view_adopted_pro/` after extraction.
`analysis/results.json` in this repository contains its saved statistics;
`analysis/original_results.json` preserves the original-label comparison.
Human verification completed after the automated analysis is documented in
`publication_state.json`. Earlier pending-status fields remain unchanged in
the original records.
