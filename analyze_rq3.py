#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ3-A · 机制归因 + 复杂度调节(纯分析,读 Phase2a 已有数据,无需 GPU/API)。
问1(归因):藏拙的缺口主要由"藏拙把弱分抬高(w↑)"还是"藏拙让真值掉下去(g↓)"驱动?
          g 的掉落又主要落在客观锚定 g_obj(没提到缺陷位置)还是盲评 g_fuzzy(没说到点子)?
问2(调节):任务越复杂(gold patch 越大 / 上下文越长),弱检查器被骗的缺口是否越大?(剂量-反应)"""
import json, argparse

def _mean(x): return sum(x) / len(x) if x else float("nan")

def spearman(xs, ys):
    def ranks(v):
        idx = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); j = 0
        while j < len(v):
            k = j
            while k + 1 < len(v) and v[idx[k + 1]] == v[idx[j]]: k += 1
            for m in range(j, k + 1): r[idx[m]] = (j + k) / 2.0 + 1
            j = k + 1
        return r
    n = len(xs)
    if n < 3: return float("nan")
    rx, ry = ranks(xs), ranks(ys); mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = (sum((rx[i] - mx) ** 2 for i in range(n)) * sum((ry[i] - my) ** 2 for i in range(n))) ** 0.5
    return num / den if den else float("nan")

def patch_lines(p):
    return sum(1 for l in p.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="results/phase2a_2026.jsonl")
    ap.add_argument("--tasks", default="data/tasks_2026_p2a160.jsonl")
    args = ap.parse_args()
    res = {r["task_id"]: r for r in (json.loads(l) for l in open(args.res, encoding="utf-8"))}
    feat = {t["task_id"]: t for t in (json.loads(l) for l in open(args.tasks, encoding="utf-8"))}

    P = [r for r in res.values() if r.get("honest", {}).get("g") is not None
         and r.get("sabotage", {}).get("g") is not None]
    hon, sab = [r["honest"] for r in P], [r["sabotage"] for r in P]
    print(f"[*] 有效配对 {len(P)}")

    # ---------- 问1:归因 ----------
    dw = _mean([s["w"] - h["w"] for h, s in zip(hon, sab)])
    dg = _mean([s["g"] - h["g"] for h, s in zip(hon, sab)])
    dgo = _mean([s["g_obj"] - h["g_obj"] for h, s in zip(hon, sab)])
    dgf = _mean([s["g_fuzzy"] - h["g_fuzzy"] for h, s in zip(hon, sab)])
    gap_h = _mean([h["w"] - h["g"] for h in hon])
    gap_s = _mean([s["w"] - s["g"] for s in sab])
    print("\n=== 问1 归因:缺口由哪端驱动 ===")
    print(f"  藏拙相对老实:Δw={dw:+.1f}(弱分抬高) | Δg={dg:+.1f}(真值掉落)")
    print(f"  → 主导端:{'真值掉落 g↓' if abs(dg) > abs(dw) else '弱分抬高 w↑'}(|Δg|={abs(dg):.1f} vs |Δw|={abs(dw):.1f})")
    print(f"  g 掉落拆分:Δg_obj={dgo:+.1f}(没提缺陷位置) | Δg_fuzzy={dgf:+.1f}(没说到点子)")
    print(f"  → g 掉落主要落在:{'客观锚定 g_obj(避开了缺陷所在文件/符号)' if abs(dgo) > abs(dgf) else '盲评 g_fuzzy(没触及根因)'}")
    print(f"  自欺缺口 w−g:老实 {gap_h:+.1f} → 藏拙 {gap_s:+.1f}(两端都被高估,藏拙更甚)")

    # ---------- 问2:复杂度调节(剂量-反应) ----------
    rows = []
    for r in P:
        t = feat.get(r["task_id"])
        if not t: continue
        rows.append({"self_gap": r["sabotage"]["w"] - r["sabotage"]["g"],       # 弱检查器对藏拙的高估
                     "exploit": (r["sabotage"]["w"] - r["honest"]["w"]) - (r["sabotage"]["g"] - r["honest"]["g"]),
                     "patch_lines": patch_lines(t.get("gold_patch", "")),
                     "ctx_chars": t.get("ctx_chars", len(t.get("code_context", ""))),
                     "n_files": len(t["hidden_defect"].get("changed_files", []))})
    print("\n=== 问2 复杂度调节(Spearman,越正=越复杂缺口越大)===")
    for proxy in ("patch_lines", "ctx_chars", "n_files"):
        xs = [x[proxy] for x in rows]
        print(f"  {proxy:<12}  vs 藏拙自欺缺口(w−g): rho={spearman(xs,[x['self_gap'] for x in rows]):+.3f}   "
              f"vs 利用增量(Δw−Δg): rho={spearman(xs,[x['exploit'] for x in rows]):+.3f}")
    # 三分位一览(用 patch_lines)
    rr = sorted(rows, key=lambda x: x["patch_lines"]); n = len(rr); t1, t2 = n // 3, 2 * n // 3
    for name, seg in (("简单", rr[:t1]), ("中等", rr[t1:t2]), ("复杂", rr[t2:])):
        print(f"    [{name}] patch行数≈{_mean([x['patch_lines'] for x in seg]):.0f}  "
              f"藏拙自欺缺口={_mean([x['self_gap'] for x in seg]):.1f}  利用增量={_mean([x['exploit'] for x in seg]):.1f}  n={len(seg)}")

if __name__ == "__main__":
    main()
