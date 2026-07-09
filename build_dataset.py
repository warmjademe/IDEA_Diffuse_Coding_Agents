#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 0 · 从 SWE-bench 构建"代码审查"任务(带隐藏标准答案)。免依赖:走 HF datasets-server JSON 接口,只用标准库。

每条任务:
  - code_context : 含真实缺陷的代码片段(gold patch 的 pre-image:上下文行+被删行),
                   **不含**修复新增行、**不含** issue 描述 —— 防答案泄漏。给生成器/弱检查器看。
  - hidden_defect: 真缺陷说明(改了哪些文件 + issue 文本)。只给"知道答案的裁判"。
  - gold_patch   : 官方修复 diff(客观锚定用)。   - tests: 相关测试(客观锚定用)。

用法: python3 build_dataset.py --n 20 --out data/tasks.jsonl
"""
import argparse, json, os, random, sys, re, urllib.request, urllib.parse, time

ROWS_API = "https://datasets-server.huggingface.co/rows"

def fetch_rows(dataset, config, split, offset, length):
    q = urllib.parse.urlencode({"dataset": dataset, "config": config,
                                "split": split, "offset": offset, "length": length})
    req = urllib.request.Request(ROWS_API + "?" + q, headers={"User-Agent": "diffuse-control-pilot"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.loads(r.read().decode())
            return [row["row"] for row in d.get("rows", [])]
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    return []

def parse_patch_preimage(patch: str):
    """从 unified diff 抽取 pre-image(上下文+被删行)与被改文件列表、修复新增行。"""
    files, blocks, added = [], [], []
    cur_file, cur_lines = None, []
    for line in patch.splitlines():
        if line.startswith('diff --git'):
            if cur_file and cur_lines:
                blocks.append((cur_file, "\n".join(cur_lines)))
            m = re.search(r' b/(\S+)', line)
            cur_file = m.group(1) if m else None
            cur_lines = []
            if cur_file:
                files.append(cur_file)
        elif line.startswith('@@'):
            cur_lines.append(line)               # 保留 hunk 头做定位
        elif line.startswith('+++') or line.startswith('---'):
            continue
        elif line.startswith('+'):
            added.append(line[1:])               # 修复新增行 → 属答案,不进 pre-image
        elif line.startswith('-'):
            cur_lines.append(line[1:])           # 被删(=原缺陷代码) → pre-image
        elif line.startswith(' '):
            cur_lines.append(line[1:])           # 上下文 → pre-image
    if cur_file and cur_lines:
        blocks.append((cur_file, "\n".join(cur_lines)))
    preimage = "\n\n".join(f"# file: {f}\n{txt}" for f, txt in blocks)
    return preimage, files, added

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    ap.add_argument("--config", default="default")
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--pool", type=int, default=100, help="先取多少条候选再筛选")
    ap.add_argument("--seed", type=int, default=20260706)
    ap.add_argument("--out", default="data/tasks.jsonl")
    args = ap.parse_args()

    print(f"[*] 拉取候选池 {args.pool} 条自 {args.dataset}:{args.split} ...", flush=True)
    pool = []
    off = 0
    while len(pool) < args.pool:
        got = fetch_rows(args.dataset, args.config, args.split, off, min(100, args.pool - len(pool)))
        if not got:
            break
        pool.extend(got)
        off += len(got)
    print(f"[*] 候选池实际 {len(pool)} 条", flush=True)

    random.Random(args.seed).shuffle(pool)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    written, leak_fail, skip_empty = 0, 0, 0
    with open(args.out, "w", encoding="utf-8") as f:
        for ex in pool:
            if written >= args.n:
                break
            patch = (ex.get("patch") or "")
            if not patch.strip():
                skip_empty += 1
                continue
            preimage, files, added = parse_patch_preimage(patch)
            if not preimage.strip() or not files:
                skip_empty += 1
                continue
            issue = (ex.get("problem_statement") or "").strip()
            # 泄漏自检:pre-image 不能出现修复新增行,也不能出现 issue 片段
            leaked = any(a.strip() and len(a.strip()) > 8 and a.strip() in preimage for a in added)
            if issue and len(issue) >= 60 and issue[:60] in preimage:
                leaked = True
            if leaked:
                leak_fail += 1
                continue
            rec = {
                "task_id": ex.get("instance_id"),
                "repo": ex.get("repo"),
                "base_commit": ex.get("base_commit"),
                "code_context": preimage,             # 给生成器/弱检查器(无答案)
                "hidden_defect": {                     # 只给"知道答案的裁判"
                    "changed_files": files,
                    "issue": issue,
                },
                "gold_patch": patch,                   # 客观锚定
                "tests": {
                    "test_patch": ex.get("test_patch", ""),
                    "fail_to_pass": ex.get("FAIL_TO_PASS", ""),
                    "pass_to_pass": ex.get("PASS_TO_PASS", ""),
                },
                "split": "val",
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    print(f"[OK] 写入 {written} 条 → {args.out}(跳过空/无效 {skip_empty},疑似泄漏 {leak_fail})", flush=True)
    if written < args.n:
        print(f"[WARN] 只凑到 {written}/{args.n},可加大 --pool 或换 Verified 集。", flush=True)

if __name__ == "__main__":
    main()
