#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案C 单任务执行器:验证一条任务的回归测试是不是有效硬信号(SWE-bench 式 fail→pass)。
流程:clone repo → checkout base_commit(buggy)→ 建 venv 装依赖 → 打 test_patch 加回归测试 →
      跑指定测试(应 FAIL)→ 再打 gold_patch(修复)→ 跑(应 PASS)。
fail_on_buggy 且 pass_on_fixed => 这条测试能捕捉该 bug = 可用硬信号案例。
本机跑(NAS 连不上 GitHub)。用法:python3 run_exec.py <task_id>"""
import json, subprocess, os, re, sys, shutil

BASE = "/tmp/claude-1000/-home-ubuntu/c7d80b93-6b5f-494c-b6ec-ba2794d5a040/scratchpad/planC"
CACHE = BASE + "/_cache"

def sh(cmd, cwd=None, timeout=600):
    r = subprocess.run(cmd, cwd=cwd, timeout=timeout, shell=isinstance(cmd, str),
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def load_task(tid):
    for line in open("data/tasks_2026.jsonl", encoding="utf-8"):
        t = json.loads(line)
        if t["task_id"] == tid:
            return t
    raise SystemExit(f"找不到任务 {tid}")

def test_names(tp):
    names = set()
    for l in tp.splitlines():
        m = re.match(r'\+\s*(?:async\s+)?def (test_\w+)', l)     # 新增的测试方法
        if m: names.add(m.group(1))
        m2 = re.search(r'@@.*\bdef (test_\w+)', l)                # hunk 上下文里的测试
        if m2: names.add(m2.group(1))
    return sorted(names)

def recon_test_patch(tp, test_files):
    if tp.lstrip().startswith("diff --git"):
        return tp
    tf = test_files[0]
    return f"diff --git a/{tf} b/{tf}\n--- a/{tf}\n+++ b/{tf}\n" + (tp if tp.endswith("\n") else tp + "\n")

def apply_patch(patch, cwd):
    p = os.path.join(cwd, "_p.diff")
    open(p, "w", encoding="utf-8").write(patch if patch.endswith("\n") else patch + "\n")
    for args in (["git", "apply", "--whitespace=nowarn", "_p.diff"],
                 ["git", "apply", "--3way", "_p.diff"],
                 ["patch", "-p1", "-i", "_p.diff"]):
        rc, out = sh(args, cwd=cwd)
        if rc == 0:
            return True, " ".join(args)
    return False, out[-400:]

def run_tests(py, repo, test_files, names, cwd):
    tf = " ".join(test_files)
    k = " or ".join(names) if names else ""
    cmd = f'"{py}" -m pytest {tf} ' + (f'-k "{k}" ' if k else "") + "-q -p no:cacheprovider --no-header"
    rc, out = sh(cmd, cwd=cwd, timeout=300)
    return rc, out

def is_collect_error(out):
    return ("error during collection" in out) or ("ImportError while importing" in out)

def heal_imports(py, pip, test_files, cwd, max_heal=8):
    """反复收集测试,缺哪个模块就 pip 装哪个,直到能收集或补不动。"""
    tf = " ".join(test_files); healed = []
    for _ in range(max_heal):
        rc, out = sh(f'"{py}" -m pytest {tf} --collect-only -q -p no:cacheprovider', cwd=cwd, timeout=180)
        if rc == 0:
            return True, healed
        m = re.search(r"No module named '([\w.]+)'", out)
        if not m:
            return False, healed                      # 非"缺模块"型收集错误,补不了
        mod = m.group(1).split('.')[0]
        if mod in healed:
            return False, healed
        # 少数 import 名≠包名,给几个常见别名
        alias = {"yaml": "pyyaml", "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn",
                 "bs4": "beautifulsoup4", "attr": "attrs"}
        sh([pip, "install", "-q", alias.get(mod, mod)], timeout=200)
        healed.append(mod)
    return False, healed

def main():
    tid = sys.argv[1]
    t = load_task(tid)
    repo, base = t["repo"], t["base_commit"]
    tests = t.get("tests", {}); test_files = tests.get("test_files", [])
    names = test_names(tests.get("test_patch", ""))
    print(f"[任务] {tid}  repo={repo}  base={base[:10]}")
    print(f"[测试] 文件={test_files}  目标测试={names or '(全跑)'}")
    if not test_files:
        print("❌ 无测试文件,跳过"); return

    os.makedirs(CACHE, exist_ok=True)
    work = f"{BASE}/{tid.replace('/','_')}"
    if os.path.exists(work): shutil.rmtree(work)
    os.makedirs(work)
    rd = work + "/repo"

    # 1) clone(带缓存)+ checkout base
    bare = f"{CACHE}/{repo.replace('/','_')}.git"
    if not os.path.exists(bare):
        rc, out = sh(["git", "clone", "--bare", "--quiet", f"https://github.com/{repo}.git", bare], timeout=600)
        if rc: print(f"❌ clone 失败: {out[-300:]}"); return
    rc, out = sh(["git", "clone", "--quiet", bare, rd], timeout=300)
    rc, out = sh(["git", "checkout", "-q", base], cwd=rd)
    if rc: print(f"❌ checkout base 失败: {out[-300:]}"); return
    print("[1] clone + checkout base ✅")

    # 2) venv + 装依赖
    venv = work + "/venv"
    sh(["python3", "-m", "venv", venv], timeout=120)
    py = venv + "/bin/python"; pip = venv + "/bin/pip"
    sh([pip, "install", "-q", "--upgrade", "pip", "setuptools", "wheel"], timeout=180)
    installed = False
    for spec in ("-e .[test]", "-e .[dev]", "-e .[testing]", "-e ."):
        rc, out = sh(f'"{pip}" install -q {spec}', cwd=rd, timeout=600)
        if rc == 0: installed = True; used = spec; break
    sh([pip, "install", "-q", "pytest"], timeout=180)
    if not installed:
        print(f"❌ 依赖安装失败(最后错误尾): {out[-400:]}"); return
    print(f"[2] venv + 装依赖 ✅ (pip install {used})")

    # 3) 打 test_patch(加回归测试)
    ok, how = apply_patch(recon_test_patch(tests["test_patch"], test_files), rd)
    if not ok: print(f"❌ test_patch 应用失败: {how}"); return
    print(f"[3] 打 test_patch ✅ ({how})")

    # 3.5) 自愈缺失测试依赖(缺哪个装哪个)
    ok_heal, healed = heal_imports(py, pip, test_files, rd)
    print(f"[3.5] 自愈测试依赖: {'✅ 可收集' if ok_heal else '⚠ 仍收集失败'}  (补装 {healed or '无'})")
    if not ok_heal:
        rc, out = sh(f'"{py}" -m pytest {" ".join(test_files)} --collect-only -q -p no:cacheprovider', cwd=rd)
        print("  收集错误尾:", out[-300:].replace(chr(10), " ")); return

    # 4) buggy 版跑测试 → 应 FAIL(rc=1 才是真失败;rc=2 收集错/rc=5 没测试 都不算)
    rc_buggy, out_b = run_tests(py, rd, test_files, names, rd)
    fail_on_buggy = (rc_buggy == 1) and not is_collect_error(out_b)
    print(f"[4] buggy 版跑测试: {'FAIL(符合预期,bug 在)' if fail_on_buggy else '未按预期失败'}  (pytest rc={rc_buggy})")

    # 5) 打 gold_patch(修复)→ 再跑 → 应 PASS
    ok, how = apply_patch(t["gold_patch"], rd)
    if not ok: print(f"❌ gold_patch 应用失败: {how}"); return
    rc_fixed, out_f = run_tests(py, rd, test_files, names, rd)
    pass_on_fixed = (rc_fixed == 0)
    print(f"[5] 修复版跑测试: {'PASS(符合预期,修好了)' if pass_on_fixed else 'FAIL(不符!)'}  (pytest rc={rc_fixed})")

    runnable = fail_on_buggy and pass_on_fixed
    if runnable:
        os.makedirs("results", exist_ok=True)
        with open("results/failures_all.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"task_id": tid, "failure": out_b[-4000:],
                                "test_files": test_files, "names": names}, ensure_ascii=False) + "\n")
    print(f"\n{'='*56}\n[结论] {tid}: {'✅ 可用硬信号案例(fail→pass 成立)' if runnable else '❌ 不可用'}")
    if not runnable:
        print("  buggy尾:", out_b[-300:].replace(chr(10), " "))
        print("  fixed尾:", out_f[-300:].replace(chr(10), " "))

if __name__ == "__main__":
    main()
