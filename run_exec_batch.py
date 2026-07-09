#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量筛"可跑硬信号案例",够 TARGET 个 或 到 MAX_ATTEMPTS 或 超时间预算 就停。
每个案例的失败输出由 run_exec.py 直接追加进 results/failures_all.jsonl,故跑完即删工作目录(省磁盘)。
用法:python3 run_exec_batch.py [TARGET=50] [MAX_ATTEMPTS=220] [TIME_BUDGET_SEC=25200]"""
import json, subprocess, sys, os, shutil, time

BASE = "/tmp/claude-1000/-home-ubuntu/c7d80b93-6b5f-494c-b6ec-ba2794d5a040/scratchpad/planC"
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 50
MAX_ATTEMPTS = int(sys.argv[2]) if len(sys.argv) > 2 else 220
TIME_BUDGET = int(sys.argv[3]) if len(sys.argv) > 3 else 25200  # 7 小时

tasks = [json.loads(l) for l in open("data/tasks_2026.jsonl", encoding="utf-8")]
val = [t for t in tasks if t.get("split") == "val"]
first = "miyuchina__mistletoe-283"
cand = [first] + [t["task_id"] for t in val if t["task_id"] != first]

os.makedirs("results", exist_ok=True)
if os.path.exists("results/failures_all.jsonl"):
    os.remove("results/failures_all.jsonl")            # 本轮重来,清空

runnable, attempts, t0 = [], 0, time.time()
for tid in cand:
    if len(runnable) >= TARGET or attempts >= MAX_ATTEMPTS or (time.time() - t0) > TIME_BUDGET:
        break
    attempts += 1
    try:
        r = subprocess.run(["python3", "run_exec.py", tid], capture_output=True, text=True, timeout=420)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = "(超时)"
    ok = "✅ 可用硬信号案例" in out
    if ok:
        runnable.append(tid)
    stage = [l for l in out.splitlines() if l.startswith("[")]
    last = stage[-1][:52] if stage else "(无输出)"
    el = int((time.time() - t0) / 60)
    print(f"[{attempts:3}] {tid:38} {'RUNNABLE ✅' if ok else '跳过    '} 累计{len(runnable):2}/{TARGET}  {el}min  末: {last}", flush=True)
    wd = f"{BASE}/{tid.replace('/', '_')}"
    shutil.rmtree(wd, ignore_errors=True)              # 失败输出已存,删目录省磁盘

json.dump({"target": TARGET, "attempts": attempts, "runnable": runnable,
           "minutes": int((time.time() - t0) / 60)},
          open("results/runnable_tasks.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n[汇总] 试 {attempts} 个,可用 {len(runnable)}/{TARGET},用时 {int((time.time()-t0)/60)}min")
print(f"[结果] results/runnable_tasks.json + results/failures_all.jsonl")
