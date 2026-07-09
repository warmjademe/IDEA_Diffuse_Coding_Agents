#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机跑:为 5 个可用案例抓"真实测试失败输出"(硬信号)。
复用批量筛选建好的 venv/仓库,git reset 回 buggy 版、重打 test_patch、跑测试,存下断言/traceback。
→ results/failures.json(task_id → 失败文本),供 NAS 上的硬检查器使用。"""
import json, os
from run_exec import sh, load_task, test_names, recon_test_patch, apply_patch, run_tests, BASE

runnable = json.load(open("results/runnable_tasks.json", encoding="utf-8"))["runnable"]
out = {}
for tid in runnable:
    t = load_task(tid)
    base = t["base_commit"]; tests = t["tests"]; tfiles = tests["test_files"]
    names = test_names(tests.get("test_patch", ""))
    work = f"{BASE}/{tid.replace('/', '_')}"; rd = work + "/repo"; py = work + "/venv/bin/python"
    if not os.path.exists(py):
        print(f"{tid}: 缺 venv,跳过"); continue
    # reset 回 buggy 版,清掉之前打的 gold/test 补丁,重打 test_patch
    sh(["git", "reset", "--hard", base], cwd=rd)
    sh(["git", "clean", "-fdq"], cwd=rd)
    ok, how = apply_patch(recon_test_patch(tests["test_patch"], tfiles), rd)
    if not ok:
        print(f"{tid}: 重打 test_patch 失败,跳过"); continue
    rc, o = run_tests(py, rd, tfiles, names, rd)
    out[tid] = {"rc": rc, "failure": o[-4000:], "test_files": tfiles, "names": names}
    print(f"{tid:38} rc={rc}(1=失败符合预期)  失败输出 {len(o)} 字")

json.dump(out, open("results/failures.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n[结果] {len(out)} 个 → results/failures.json")
