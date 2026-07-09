#!/bin/bash
# 过夜方案C:本机挖50可跑案例 → 传NAS → NAS多样本hard-vs-soft → 拉回 → 自Bark。
# 对 NAS SSH 瞬时断连容错(重试+冷却)。自包含。
cd /home/ubuntu/RESEARCH/IDEA_Diffuse_Coding_Agents/Source_Codes || exit 1
BARK="https://api.day.app/YOUR_BARK_KEY"
SRC="~/IDEA_Diffuse_Coding_Agents/Source_Codes"
SSHOPT="-o StrictHostKeyChecking=no -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=6"

# 重试包装:最多 8 次,每次间隔 15s(容忍限流/瞬断)
retry() { local i; for i in $(seq 1 8); do "$@" && return 0; echo "  [retry $i] $* 失败,15s后重试"; sleep 15; done; return 1; }
ssh_nas() { sshpass -p 'YOUR_NAS_PASSWORD' ssh $SSHOPT user@YOUR_NAS_HOST "$@"; }
rsync_up() { sshpass -p 'YOUR_NAS_PASSWORD' rsync -az -e "ssh $SSHOPT" "$@" user@YOUR_NAS_HOST:$SRC/; }
rsync_dn() { sshpass -p 'YOUR_NAS_PASSWORD' rsync -az -e "ssh $SSHOPT" user@YOUR_NAS_HOST:$SRC/"$1" results/; }

echo "===== [Phase1] 本机挖 50 可跑案例  $(date) ====="
python3 -u run_exec_batch.py 50 220 25200

N=$(wc -l < results/failures_all.jsonl 2>/dev/null || echo 0)
echo "===== 挖到 $N 个可用案例  $(date) ====="
if [ "$N" -lt 3 ]; then
  curl -s "$BARK/planC-mining-only-$N-abort" >/dev/null 2>&1
  echo "可用案例太少($N),终止"; exit 1
fi

echo "===== 传 NAS  $(date) ====="
retry rsync_up results/failures_all.jsonl results/runnable_tasks.json run_hvs_multi.py || { curl -s "$BARK/planC-rsync-up-failed"; exit 1; }
retry ssh_nas "cd $SRC && mkdir -p results && mv -f failures_all.jsonl runnable_tasks.json results/ 2>/dev/null; wc -l results/failures_all.jsonl"

echo "===== [Phase2] NAS 多样本 hard-vs-soft  $(date) ====="
retry ssh_nas "cd $SRC && setsid bash -c 'source ~/.diffuse_env; python3 -u run_hvs_multi.py > results/hvs50.log 2>&1; echo ___HVS50_DONE___ >> results/hvs50.log' >/dev/null 2>&1 &"
# 轮询(对断连容错:ssh 失败当作未完成,继续等;最多 ~4h)
for i in $(seq 1 240); do
  if ssh_nas "grep -q ___HVS50_DONE___ $SRC/results/hvs50.log 2>/dev/null"; then echo "Phase2 完成"; break; fi
  sleep 60
done

echo "===== 拉结果  $(date) ====="
retry rsync_dn results/hvs50.log
retry rsync_dn results/hvs50.json
echo "===== DONE  $(date) ====="
tail -16 results/hvs50.log
curl -s "$BARK/planC-overnight-done-N${N}" >/dev/null 2>&1
