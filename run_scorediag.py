#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断:自适应终版说明书如何给"老实 vs 藏拙"两种意图打分,取真实样例逐条展示。
对每个验证任务:老实审查(复用 bank_val)+ 红队白盒藏拙审查(现造,专攻自适应说明书),
分别用 默认说明书 与 自适应终版说明书 打弱分 w,并给出真值 g 与审查片段。
用来解释为什么自适应臂出现"藏拙缺口 36.2、老实均分 28.7"。"""
import json, sys
import scorers
from run_coevolve import red_adapt_review
from run_phase3 import _load_split

def snip(t, n=140):
    return (t or "").replace("\n", " ").strip()[:n]

def main():
    n_tasks = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ada = open("results/coevolve_adaptive_rubric.txt", encoding="utf-8").read().strip()
    dft = scorers.DEFAULT_BLUE_RUBRIC
    print("=== 自适应终版说明书(节选)===")
    print(ada[:700].replace("{code}", "〈代码〉").replace("{review}", "〈审查〉"), "...\n")

    val = _load_split("data/tasks_2026.jsonl", "val", 40)
    honest = {b["task_id"]: b for b in (json.loads(l) for l in open("results/bank_val.jsonl", encoding="utf-8"))
              if b["arm"] == "honest"}
    picks = [t for t in val if t["task_id"] in honest][:n_tasks]

    def w(rev, rubric, code):
        return scorers.score_weak({"code_context": code}, rev, blue_rubric=rubric)

    for i, t in enumerate(picks, 1):
        h = honest[t["task_id"]]
        files, syms = scorers._targets_from_patch(t)
        sab = red_adapt_review(t, ada)                       # 白盒藏拙:专攻自适应说明书
        go, _ = scorers.score_objective(t, sab); gf = scorers.score_gt_fuzzy(t, sab)
        sab_g = round(0.5 * go + 0.5 * (gf if gf is not None else 0), 1)
        print(f"\n{'='*70}\n[任务 {i}] {t['task_id']}")
        print(f"  真实缺陷位置(应被点到): 文件/符号={', '.join((files+syms)[:6])}")
        print(f"  问题: {snip(t['hidden_defect'].get('issue',''), 110)}")
        for label, rev, g in [("老实   ", h["review"], h["g"]), ("藏拙(白盒)", sab, sab_g)]:
            wd = w(rev, dft, t["code_context"]); wa = w(rev, ada, t["code_context"])
            print(f"  ── {label} | 真值 g={g:>5} | 默认说明书 w={wd} | 自适应说明书 w={wa}")
            print(f"       审查片段: {snip(rev)}")

if __name__ == "__main__":
    main()
