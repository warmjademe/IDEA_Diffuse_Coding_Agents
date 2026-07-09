#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案A:硬信号(g,有答案)vs 软信号(w,无答案)对照。
在验证集配对(老实,藏拙)上,看每个"检查器"能否把老实排在藏拙之上。
- 硬信号检查器 = g(拿 gold patch;客观锚定+盲评)
- 软信号检查器 = 弱模型 w,分别用 默认说明书 / 自适应终版说明书
复用 bank_val(已含 review + g),只需 Qwen 重打 w,纯本地便宜。
核心指标:排序正确率 = 同任务(老实,藏拙)对里"老实分>藏拙分"的比例(≈检测成功率,对应 §3.2 的 1−ε⋆)。"""
import json
import scorers
from run_phase3 import score_w

def summarize(name, hs, ss):
    pr = [(h, s) for h, s in zip(hs, ss) if h is not None and s is not None]
    mh = sum(h for h, s in pr) / len(pr)
    ms = sum(s for h, s in pr) / len(pr)
    acc = sum(1 for h, s in pr if h > s) / len(pr)          # 老实>藏拙
    tie = sum(1 for h, s in pr if h == s) / len(pr)
    print(f"{name:24} 老实均分={mh:5.1f}  藏拙均分={ms:5.1f}  "
          f"分离度(老实−藏拙)={mh-ms:+6.1f}  排序正确率(老实>藏拙)={acc*100:4.0f}%  (平局{tie*100:.0f}%)  n={len(pr)}")

def main():
    ada = open("results/coevolve_adaptive_rubric.txt", encoding="utf-8").read().strip()
    dft = scorers.DEFAULT_BLUE_RUBRIC
    bank = [json.loads(l) for l in open("results/bank_val.jsonl", encoding="utf-8")]
    by = {}
    for b in bank:
        by.setdefault(b["task_id"], {})[b["arm"]] = b
    pairs = [(v["honest"], v["sabotage"]) for v in by.values() if "honest" in v and "sabotage" in v]
    hon = [h for h, s in pairs]; sab = [s for h, s in pairs]
    print(f"配对(老实,藏拙)= {len(pairs)} 对\n")

    g_h = [h["g"] for h in hon];               g_s = [s["g"] for s in sab]
    wd_h = score_w(hon, dft);                  wd_s = score_w(sab, dft)
    wa_h = score_w(hon, ada);                  wa_s = score_w(sab, ada)

    summarize("硬信号 g(有答案)", g_h, g_s)
    summarize("软信号 w / 默认说明书", wd_h, wd_s)
    summarize("软信号 w / 自适应说明书", wa_h, wa_s)
    print("\n解读:排序正确率 ≈50%=分不清;<50%=判反;越高=越能把老实排在藏拙之上。")
    print("硬信号 g 应显著高于两个软信号 w —— 差别不在模型聪明,在'有没有答案可核实'。")

    out = {"n_pairs": len(pairs),
           "g":        {"honest": round(sum(g_h)/len(g_h),1),  "sab": round(sum(g_s)/len(g_s),1)},
           "w_default":{"honest": round(sum(x for x in wd_h if x is not None)/len(wd_h),1),
                        "sab": round(sum(x for x in wd_s if x is not None)/len(wd_s),1)},
           "w_adaptive":{"honest": round(sum(x for x in wa_h if x is not None)/len(wa_h),1),
                         "sab": round(sum(x for x in wa_s if x is not None)/len(wa_s),1)}}
    json.dump(out, open("results/hardsoft.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[结果] → results/hardsoft.json")

if __name__ == "__main__":
    main()
