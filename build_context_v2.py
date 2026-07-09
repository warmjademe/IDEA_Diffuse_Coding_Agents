#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0-v2 · 加厚代码上下文。读现有 data/tasks.jsonl,用 GitHub raw 抓 base_commit 时刻的完整文件,
截取每个改动附近的较大区域(默认 ±55 行)当 code_context,替换掉原来的 diff 碎片。
在**本机**跑(本机可达 GitHub raw;NAS 不可达)。保证:base_commit 是修复前版本 → 不含 fix;不含 issue 文本。"""
import argparse, json, os, re, sys, urllib.request, time

CTX = 55            # 改动上下各取多少行
CAP_FILE = 8000     # 每文件上限字符
CAP_TOTAL = 12000   # 每任务上限字符

def fetch_raw(repo, sha, path, retries=3):
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ctx-v2"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            time.sleep(2 * (a + 1))
    return None

def hunks_by_file(patch):
    """返回 {path: [(old_start, old_count), ...]}。"""
    out, cur = {}, None
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            m = re.search(r' b/(\S+)', line); cur = m.group(1) if m else None
            if cur: out.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            m = re.search(r'@@ -(\d+)(?:,(\d+))? ', line)
            if m:
                out[cur].append((int(m.group(1)), int(m.group(2) or 1)))
    return out

def extract_windows(text, hunks):
    lines = text.splitlines()
    keep = set()
    for (s, c) in hunks:
        lo = max(0, s - 1 - CTX); hi = min(len(lines), s - 1 + c + CTX)
        keep.update(range(lo, hi))
    if not keep:
        return ""
    idx = sorted(keep)
    out, prev = [], None
    for i in idx:
        if prev is not None and i > prev + 1:
            out.append("        ...")     # 区段间断裂标记
        out.append(lines[i]); prev = i
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="data/tasks.jsonl")
    ap.add_argument("--out", default="data/tasks_v2.jsonl")
    args = ap.parse_args()
    tasks = [json.loads(l) for l in open(args.inp, encoding="utf-8")]
    print(f"[*] 加厚 {len(tasks)} 条上下文(GitHub raw @ base_commit)...", flush=True)

    written, leak_fail, fetch_fail = 0, 0, 0
    with open(args.out, "w", encoding="utf-8") as f:
        for t in tasks:
            repo, sha, patch = t["repo"], t["base_commit"], t["gold_patch"]
            hbf = hunks_by_file(patch)
            issue = (t["hidden_defect"].get("issue") or "")
            added = [l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")]
            parts, total = [], 0
            for path, hunks in hbf.items():
                raw = fetch_raw(repo, sha, path)
                if raw is None:
                    fetch_fail += 1; continue
                win = extract_windows(raw, hunks)[:CAP_FILE]
                if not win.strip():
                    continue
                block = f"# file: {path}\n{win}"
                if total + len(block) > CAP_TOTAL:
                    block = block[:max(0, CAP_TOTAL - total)]
                parts.append(block); total += len(block)
                if total >= CAP_TOTAL:
                    break
            ctx = "\n\n".join(parts).strip()
            if not ctx:
                continue
            # 泄漏自检:base_commit 版本不该含修复新增行;不该含 issue 片段
            leaked = any(a.strip() and len(a.strip()) > 10 and a.strip() in ctx for a in added)
            if issue and len(issue) >= 60 and issue[:60] in ctx:
                leaked = True
            if leaked:
                leak_fail += 1; continue
            t2 = dict(t); t2["code_context"] = ctx; t2["ctx_chars"] = len(ctx)
            f.write(json.dumps(t2, ensure_ascii=False) + "\n"); written += 1
            print(f"  {t['task_id'][:32]:<34} ctx={len(ctx)}字符", flush=True)
    print(f"[OK] 写 {written} 条 → {args.out}(抓取失败 {fetch_fail},疑似泄漏跳过 {leak_fail})", flush=True)

if __name__ == "__main__":
    main()
