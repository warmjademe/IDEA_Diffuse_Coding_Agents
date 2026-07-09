#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1 · 老实基线:多个不同强弱的生成器各自老实产审查,用 w / g 打分。
验收:跨生成器时 w 与 g 正相关(w 不是纯噪),且 g 能把"真实生成器"排在"平凡基线"之上。"""
import json, os, sys, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import scorers
from common.api import cost_report

# 生成器梯度(强 → 弱 → 平凡地板)。provider=None 表示不调 API(平凡基线)。
GENERATORS = [
    ("deepseek-v4-pro",   "deepseek"),
    ("deepseek-v4-flash", "deepseek"),
    ("qwen-coder",        "qwen_coder_nas"),
    ("trivial",           None),
]

def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx > 0 and dy > 0 else float("nan")

def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r

def spearman(xs, ys):
    return pearson(_ranks(xs), _ranks(ys))

def one_job(task, gen_model, gen_provider):
    review = scorers.TRIVIAL_REVIEW if gen_provider is None else scorers.run_generator(task, gen_provider, gen_model)
    w = scorers.score_weak(task, review)
    g_obj, obj_meta = scorers.score_objective(task, review)
    g_fuzzy = scorers.score_gt_fuzzy(task, review)
    g = None
    if g_fuzzy is not None:
        g = round(0.5 * g_obj + 0.5 * g_fuzzy, 1)
    return {"gen": gen_model, "task_id": task["task_id"], "w": w,
            "g_obj": g_obj, "g_fuzzy": g_fuzzy, "g": g,
            "obj_meta": obj_meta, "review_len": len(review or "")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="data/tasks.jsonl")
    ap.add_argument("--out", default="results/phase1_baseline.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help=">0 则只跑前 N 条任务(调试用)")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in open(args.tasks, encoding="utf-8")]
    if args.limit > 0:
        tasks = tasks[:args.limit]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    jobs = [(t, gm, gp) for gm, gp in GENERATORS for t in tasks]
    print(f"[*] {len(tasks)} 任务 × {len(GENERATORS)} 生成器 = {len(jobs)} 个作业,{args.workers} 并发", flush=True)

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one_job, t, gm, gp): (gm, t["task_id"]) for t, gm, gp in jobs}
        done = 0
        for fu in as_completed(futs):
            try:
                rows.append(fu.result())
            except Exception as e:
                gm, tid = futs[fu]
                rows.append({"gen": gm, "task_id": tid, "w": None, "g": None, "error": str(e)})
            done += 1
            if done % 10 == 0:
                print(f"    {done}/{len(jobs)}", flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- 统计 ----
    def valid(r):
        return r.get("w") is not None and r.get("g") is not None
    good = [r for r in rows if valid(r)]
    fail = len(rows) - len(good)
    print("\n" + "=" * 64)
    print(f"有效 {len(good)}/{len(rows)}(失败/缺分 {fail})")
    print(f"{'生成器':<20}{'mean_w':>8}{'mean_g':>8}{'mean_g_obj':>12}{'mean_g_fuzzy':>13}  n")
    per_gen_mean_g = {}
    for gm, _ in GENERATORS:
        sub = [r for r in good if r["gen"] == gm]
        if not sub:
            print(f"{gm:<20}{'-':>8}{'-':>8}   (无有效)"); continue
        mw = sum(r["w"] for r in sub) / len(sub)
        mg = sum(r["g"] for r in sub) / len(sub)
        mo = sum(r["g_obj"] for r in sub) / len(sub)
        mfz = sum(r["g_fuzzy"] for r in sub) / len(sub)
        per_gen_mean_g[gm] = mg
        print(f"{gm:<20}{mw:>8.1f}{mg:>8.1f}{mo:>12.1f}{mfz:>13.1f}  {len(sub)}")

    ws = [r["w"] for r in good]; gs = [r["g"] for r in good]
    gobj = [r["g_obj"] for r in good]; gfz = [r["g_fuzzy"] for r in good]
    p_wg, s_wg = pearson(ws, gs), spearman(ws, gs)
    print(f"\n跨生成器  corr(w, g):        Pearson {p_wg:.3f}   Spearman {s_wg:.3f}")
    print(f"          corr(w, g_obj):    Pearson {pearson(ws, gobj):.3f}")
    print(f"          corr(w, g_fuzzy):  Pearson {pearson(ws, gfz):.3f}")
    # 组内相关(论文发现组内几乎消失)
    print("  组内 corr(w,g):", end=" ")
    for gm, _ in GENERATORS:
        sub = [r for r in good if r["gen"] == gm]
        if len(sub) >= 3:
            print(f"{gm}={pearson([r['w'] for r in sub],[r['g'] for r in sub]):.2f}", end="  ")
    print()

    # ---- 验收判定 ----
    real = [g for g in ("deepseek-v4-pro", "deepseek-v4-flash", "qwen-coder") if g in per_gen_mean_g]
    rank_ok = ("trivial" in per_gen_mean_g and real and
               min(per_gen_mean_g[g] for g in real) >= per_gen_mean_g["trivial"] - 1e-6)
    noise_ok = (p_wg == p_wg and p_wg > 0.15)          # 跨生成器 w 与 g 正相关 → 不是纯噪
    fail_ok = (fail / max(1, len(rows))) < 0.15
    print("\n[验收]")
    print(f"  ① w 不是纯噪(跨生成器 Pearson>0.15): {'PASS' if noise_ok else 'FAIL'}  ({p_wg:.3f})")
    print(f"  ② g 把真实生成器排在平凡基线之上:     {'PASS' if rank_ok else 'FAIL'}")
    print(f"  ③ 失败率 <15%:                        {'PASS' if fail_ok else 'FAIL'}  ({fail}/{len(rows)})")
    print(f"  => Phase 1 {'通过 ✅' if (noise_ok and rank_ok and fail_ok) else '未通过,需修 rubric/管道 ❌'}")
    print("\n[成本]", cost_report())
    print(f"[结果] 明细 → {args.out}")

if __name__ == "__main__":
    main()
