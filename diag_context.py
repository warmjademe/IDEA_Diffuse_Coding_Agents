#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断:5 个可用案例的 code_context 有没有框住 bug。
逻辑:gold_patch 里被删的"-"行 = 原始 buggy 代码;若它们在 code_context 里出现,说明上下文框住了 bug,
honest 看得到却没找到 = 生成问题;若不在,则是 context 窗口没框住 bug = 系统性取材问题。"""
import json, re

TIDS = ["miyuchina__mistletoe-283", "ilpomo__pomata-76", "AnswerDotAI__ipythonng-7",
        "QuantEcon__QuantEcon.py-842", "gittensor-vanguard__vanguarstew-198"]
tasks = {t["task_id"]: t for t in (json.loads(l) for l in open("data/tasks_2026.jsonl", encoding="utf-8"))
         if t["task_id"] in TIDS}

def norm(s):  # 归一化空白,避免缩进差异误判
    return re.sub(r"\s+", " ", s).strip()

for tid in TIDS:
    t = tasks[tid]
    ctx = t["code_context"]; ctx_n = norm(ctx)
    gp = t["gold_patch"]; cf = t["hidden_defect"]["changed_files"]
    removed = [l[1:] for l in gp.splitlines() if l.startswith("-") and not l.startswith("---")]
    removed = [l for l in removed if len(l.strip()) > 6]                 # 忽略太短的行
    added = [l[1:] for l in gp.splitlines() if l.startswith("+") and not l.startswith("+++") and len(l[1:].strip()) > 6]
    funcs = set(re.findall(r'@@.*@@\s*(?:async\s+)?(?:def|class)?\s*([A-Za-z_]\w+)', gp))
    rem_hit = sum(1 for l in removed if norm(l) and norm(l) in ctx_n)
    func_hit = [f for f in funcs if f in ctx]
    file_hit = [f for f in cf if f.split("/")[-1] in ctx or f.split("/")[-1].rsplit(".", 1)[0] in ctx]
    verdict = "✅ 框住了 bug" if (removed and rem_hit > 0) else ("⚠ 无被删行可判" if not removed else "❌ 没框住 bug")
    print(f"\n{'='*66}\n[{tid}]")
    print(f"  ctx长度={len(ctx)}  改动文件={cf}")
    print(f"  gold改动函数/类={sorted(funcs)[:6] or '(未解析到)'}  其中在ctx里={func_hit}")
    print(f"  改动文件名出现在ctx: {'是' if file_hit else '否'}")
    print(f"  被删(原buggy)行 {len(removed)} 条 → 在ctx出现 {rem_hit} 条 ⇒ {verdict}")
    if removed:
        print(f"  示例被删行: {removed[0].strip()[:90]}")
