#!/bin/bash
# RQ6 FULL(生成器=Claude Sonnet 5)n=160, K=3。detached 跑,结尾自 Bark。
cd ~/IDEA_Diffuse_Coding_Agents/Source_Codes || exit 1
source ~/.diffuse_env
BARK="https://api.day.app/YOUR_BARK_KEY"
t0=$(date +%s)
python3 run_rq6_sonnet5.py --tasks data/tasks_2026_p2a160.jsonl --k 3 --workers 6 \
    --out results/rq6_sonnet5.json --detail results/rq6_sonnet5_detail.jsonl \
    > results/rq6_sonnet5.log 2>&1
rc=$?
el=$(( ($(date +%s) - t0) / 60 ))
# 提取关键结论行推送
verdict=$(grep -E "RQ6 判定|拒绝率:" results/rq6_sonnet5.log | tr '\n' ' ' | head -c 300)
if [ $rc -eq 0 ]; then
    curl -s "$BARK/RQ6-Sonnet5%20FULL%20done%20(${el}min)::%20$(echo "$verdict" | sed 's/ /%20/g')" >/dev/null
else
    curl -s "$BARK/RQ6-Sonnet5%20FULL%20FAILED%20rc=${rc}%20(${el}min)" >/dev/null
fi
