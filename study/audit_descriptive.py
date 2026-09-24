"""Read-only descriptive audit of frozen original and adopted-label results.

Run with the original experiment root as argv[1]. No model calls, label edits,
threshold tuning, or new hypothesis tests are performed.
"""
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "code"))
import analyze
import numpy as np


def describe(rows):
    out = {"requested": len(rows), "tasks": len({r["task_id"] for r in rows}),
           "usable": sum(r["y"] in (0, 1) and r["score"] is not None for r in rows)}
    for metric in ("fpr", "fnr", "joint_harmful_accepted", "mean_score"):
        num, den = analyze.metric_vectors(rows, metric)
        out[metric] = {"numerator": float(sum(num)), "denominator": float(sum(den)),
                       "estimate": analyze.ratio(sum(num), sum(den))}
    for metric in ("auroc", "spearman"):
        out[metric] = analyze.association(rows, metric)
    scores = [r["score"] for r in rows if r["score"] is not None]
    out["score_distribution"] = {
        "min": min(scores) if scores else None, "max": max(scores) if scores else None,
        "sample_sd": float(np.std(scores, ddof=1)) if len(scores) > 1 else None,
        "distinct_scores": len(set(scores))}
    return out


def matched_panel(rows, conditions):
    matrix = {(r["key"], r["condition"]): r for r in rows}
    keys = sorted({r["key"] for r in rows})
    usable = [k for k in keys if all((k, c) in matrix and
              matrix[k, c]["y"] in (0, 1) and matrix[k, c]["score"] is not None
              for c in conditions)]
    for k in usable:
        assert len({matrix[k, c]["y"] for c in conditions}) == 1
    # Check the library AUROC against a direct positive/negative pair count.
    # Also independently verify the operational FPR/FNR denominators.
    for c in conditions:
        current = [matrix[k, c] for k in usable]
        pos = [r for r in current if r["y"] == 1]
        neg = [r for r in current if r["y"] == 0]
        direct_auc = sum((a["score"] > b["score"]) + .5 * (a["score"] == b["score"])
                         for a in pos for b in neg) / (len(pos) * len(neg))
        stat = describe(current)
        assert abs(direct_auc - stat["auroc"]) < 1e-12
        assert stat["fpr"]["numerator"] == sum(r["score"] >= r["threshold"] for r in neg)
        assert stat["fpr"]["denominator"] == len(neg)
        assert stat["fnr"]["numerator"] == sum(r["score"] < r["threshold"] for r in pos)
        assert stat["fnr"]["denominator"] == len(pos)
    return {"common_n": len(usable), "conditions": {
        c: describe([matrix[k, c] for k in usable]) for c in conditions}}


def audit(view):
    rows = analyze.load_rows(view)
    py = [r for r in rows if r["language"] == "Python"]
    normal = [r for r in py if r["strategy"] is None]
    fixed = [r for r in py if r["strategy"] is None or r["paired_panel"]]
    java = [r for r in rows if r["language"] == "Java"]
    conditions = [f"{m}/{d}" for m in ("haiku", "mini", "gpt") for d in ("D1", "D5")]
    result = {"row_count": len(rows), "normal_python": {},
              "python_common_six_conditions": matched_panel(fixed, conditions),
              "python_per_checker_matched": {},
              "java_matched": matched_panel(java, ["haiku/D1", "haiku/D5"]),
              "adaptive_pooled_descriptive": {}, "normal_D4_matched": {}}
    for condition in sorted({r["condition"] for r in normal}):
        result["normal_python"][condition] = describe([r for r in normal if r["condition"] == condition])
    for model in ("haiku", "mini", "gpt"):
        result["python_per_checker_matched"][model] = matched_panel(fixed, [f"{model}/D1", f"{model}/D5"])
    for model in ("haiku", "gpt"):
        for defense in ("D1", "D4", "D5"):
            group = [r for r in py if r["strategy"] is not None and r["target"] == model
                     and r["defense"] == defense and r["condition"] == f"{model}/{defense}"]
            stat = describe(group)
            per_run = [describe([r for r in group if r["repetition"] == i]) for i in (1, 2, 3)]
            values = [x["joint_harmful_accepted"]["estimate"] for x in per_run]
            stat["three_run_joint"] = {"values": values, "mean": float(np.mean(values)),
                                        "sample_sd": float(np.std(values, ddof=1))}
            result["adaptive_pooled_descriptive"][f"{model}/{defense}"] = stat
        matrix = {(r["key"], r["condition"]): r for r in normal}
        left, right = [], []
        for key in sorted({r["key"] for r in normal}):
            for run in (1, 2, 3):
                a, b = matrix.get((key, f"{model}/D1")), matrix.get((key, f"{model}/D4/run{run}"))
                if a and b and a["score"] is not None and b["score"] is not None:
                    left.append(a)
                    right.append(b)
        result["normal_D4_matched"][model] = {"D1_repeated_per_run": describe(left),
                                                "D4": describe(right)}
    return result


views = {"original_flash": root,
         "adopted_pro": root / "supplement/20260924_audit_gaps/analysis_view_adopted_pro"}
output = {"scope": "Descriptive aggregation; existing frozen tests used for inferential claims.",
          "verification": "All matched-panel AUROC, FPR and FNR independently checked by direct counts.",
          "views": {}, "source_hashes": {}, "paired_test_sensitivity": {}}
stats = {}
for name, view in views.items():
    source = view / "analysis/results.json"
    output["source_hashes"][name] = hashlib.sha256(source.read_bytes()).hexdigest()
    stats[name] = json.loads(source.read_text())["automatic_reference"]
    output["views"][name] = audit(view)
for family, new in stats["adopted_pro"]["paired_tests"].items():
    old = {t["name"]: t for t in stats["original_flash"]["paired_tests"][family]}
    changed_significance, sign_flips, became_zero = [], [], []
    differences = []
    for test in new:
        before = old[test["name"]]
        if (before["q_bh"] < .05) != (test["q_bh"] < .05):
            changed_significance.append(test["name"])
        if before["difference"] * test["difference"] < 0:
            sign_flips.append(test["name"])
        if before["difference"] != 0 and test["difference"] == 0:
            became_zero.append(test["name"])
        differences.append(abs(before["difference"] - test["difference"]))
    output["paired_test_sensitivity"][family] = {
        "test_count": len(new), "changed_q_below_005": changed_significance,
        "strict_sign_flips": sign_flips, "became_zero": became_zero,
        "max_absolute_effect_change": max(differences)}
print(json.dumps(output, ensure_ascii=False, indent=2))
