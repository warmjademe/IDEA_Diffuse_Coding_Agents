#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看低分 honest 审查到底说了啥:是"看得到 bug 却诊断了别的"(生成问题),还是 g 误判。"""
import json, re
import scorers

TIDS = ["AnswerDotAI__ipythonng-7", "QuantEcon__QuantEcon.py-842", "gittensor-vanguard__vanguarstew-198"]
tasks = {t["task_id"]: t for t in (json.loads(l) for l in open("data/tasks_2026.jsonl", encoding="utf-8"))
         if t["task_id"] in TIDS}
for tid in TIDS:
    t = tasks[tid]
    funcs = sorted(set(re.findall(r'@@.*@@\s*(?:async\s+)?(?:def|class)?\s*([A-Za-z_]\w+)', t["gold_patch"])))
    rev = scorers.run_generator(t, "deepseek", "deepseek-v4-pro", tmpl=scorers.BENIGN_GEN_TMPL)
    go, det = scorers.score_objective(t, rev)
    gf = scorers.score_gt_fuzzy(t, rev)
    mentions = [f for f in funcs if f in (rev or "")]
    print(f"\n{'='*66}\n[{tid}] 改动函数={funcs}")
    print(f"  issue: {(t['hidden_defect'].get('issue','') or '')[:130]}")
    print(f"  honest: g_obj={go} g_fuzzy={gf}  审查里提到改动函数={mentions or '无'}")
    print(f"  honest审查(前450字): {(rev or '')[:450].strip()}")
