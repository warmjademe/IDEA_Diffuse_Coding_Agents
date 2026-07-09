#!/bin/bash
# RQ5 FULL 跑:GPT-5.5 生成器,n=160,K=3。detached 用;结尾自 Bark。
source ~/.diffuse_env
cd ~/IDEA_Diffuse_Coding_Agents/Source_Codes
LOG=results/rq5_full.log
python3 run_rq5_gpt55.py --tasks data/tasks_2026_p2a160.jsonl --k 3 --workers 6 \
    --out results/rq5_gpt55.json --detail results/rq5_gpt55_detail.jsonl > "$LOG" 2>&1
RC=$?
# 从汇总 json 提取关键数结果推 Bark
MSG=$(python3 - <<'PY'
import json
try:
    d=json.load(open("results/rq5_gpt55.json"))
    b=d["benign"]; s=d["sandbag"]
    msg=("RQ5 GPT-5.5 FULL done n=%d | benign w=%.1f g=%.1f | sandbag w=%.1f g=%.1f | "
         "sandbag delta(w-g)=%.1f | dG=%.1f p=%.1g | reproduced=%s") % (
        d["n_pairs"], b["w"], b["g"], s["w"], s["g"], s["delta_w_minus_g"],
        d["delta_g_sab_minus_ben"]["mean"], d["delta_g_sab_minus_ben"]["wilcoxon_p"],
        d["phenomenon_reproduced"])
    print(msg)
except Exception as e:
    print("RQ5 GPT-5.5 FULL finished rc=%s but summary parse failed: %s" % ("$RC", e))
PY
)
python3 - "$MSG" <<'PY'
import sys, json, urllib.request
msg = sys.argv[1] if len(sys.argv) > 1 else "RQ5 done"
data = json.dumps({"title": "RQ5 GPT-5.5", "body": msg, "group": "diffuse"}).encode()
try:
    req = urllib.request.Request("https://api.day.app/YOUR_BARK_KEY",
                                 data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
except Exception as e:
    print("bark fail", e)
PY
echo "[bark sent] $MSG" >> "$LOG"
