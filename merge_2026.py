#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并双 token 并行采集的分片:去重(按 task_id)、按 merged_at 从新到旧排序、
截到 total、最新的 val 条作验证集、其余训练。"""
import argparse, json

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", default="data/tasks_2026.jsonl")
    ap.add_argument("--val", type=int, default=300)
    ap.add_argument("--total", type=int, default=2700)
    args = ap.parse_args()

    seen, rows = set(), []
    for path in args.inputs:
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                tid = r.get("task_id")
                if tid in seen:
                    continue
                seen.add(tid); rows.append(r)
        except FileNotFoundError:
            print(f"[warn] 缺分片 {path}")
    rows.sort(key=lambda r: r.get("merged_at") or "", reverse=True)   # 新→旧
    rows = rows[:args.total]
    for i, r in enumerate(rows):
        r["split"] = "val" if i < args.val else "train"
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    nval = sum(1 for r in rows if r["split"] == "val")
    print(f"[OK] 合并去重后 {len(rows)} 条 → {args.out}(验证 {nval} / 训练 {len(rows)-nval})")
    if rows:
        print(f"     时间跨度: {rows[-1].get('merged_at')} ~ {rows[0].get('merged_at')}")

if __name__ == "__main__":
    main()
