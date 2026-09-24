# Release verification (2026-09-24)

Verification used an isolated NAS directory reconstructed from the public
archives, leaving the original experiment directory unchanged.

- All 22,298 archived files matched their manifest SHA-256 hashes.
- All group estimates, bootstrap intervals, 38 paired tests, and the two Pro
  passes matched the saved analysis (numeric tolerance 1e-11).
- The additional publication aggregates, common-panel estimates, sample flows,
  raw usage totals, and descriptive checks matched their saved counterparts.
- Direct positive/negative pair counts independently reproduced AUROC, FPR and
  FNR denominators for the matched panels.
- All six final D4 rubric strings matched the initial D1 rubric exactly.
- The 27 frozen offline tests passed, including parsing, pairing, thresholds,
  ledger concurrency, and stagnation recovery.
- All five generated result tables matched the manuscript table source.
- Credential scans covered every decompressed archive member and the new source
  and documentation files; no credential-shaped content was found.

These checks make no inference API calls and do not manufacture human ratings.
Author-confirmed human review is described separately in `publication_state.json`.
