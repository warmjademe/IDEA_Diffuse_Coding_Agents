#!/usr/bin/env bash
# 在 NAS 上用 vLLM 起 Qwen Coder 作"弱检查器"(便宜实习生)。目标:单张 RTX 4090 (24GB)。
# 用法:  bash start_qwen_vllm.sh              # 用默认 14B-AWQ 起
#         MODEL=Qwen/Qwen2.5-Coder-1.5B bash start_qwen_vllm.sh   # 换更弱的
#         bash start_qwen_vllm.sh stop         # 停掉
set -eo pipefail   # 不用 -u:conda 激活钩子会引用未定义的 NVCC_PREPEND_FLAGS,严格模式下会误杀

# ---- 可调参数(环境变量覆盖)----
MODEL="${MODEL:-Qwen/Qwen2.5-Coder-14B-Instruct-AWQ}"   # 弱检查器默认;备选见文末
SERVED_NAME="${SERVED_NAME:-qwen-coder}"                  # 对齐 config.yaml
SERVE_HOST="${SERVE_HOST:-127.0.0.1}"          # 本机监听更安全;要跨机访问改 0.0.0.0 或走 SSH 隧道
SERVE_PORT="${SERVE_PORT:-8000}"
MAXLEN="${MAXLEN:-16384}"          # 上下文长度;本项目任务很短,16k 足够
GPU_UTIL="${GPU_UTIL:-0.90}"
ENV_NAME="${ENV_NAME:-EMNLP_2026_Overeage}"   # 已装 vLLM 的 conda 环境
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
WORKDIR="$HOME/IDEA_Diffuse_Coding_Agents"
LOG="${LOG:-$WORKDIR/qwen_vllm.log}"
PIDFILE="$WORKDIR/qwen_vllm.pid"

mkdir -p "$WORKDIR"

# ---- stop 子命令 ----
if [ "${1:-}" = "stop" ]; then
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")" && echo "[OK] 已停 PID $(cat "$PIDFILE")"; rm -f "$PIDFILE"
  else
    pkill -f "vllm serve $MODEL" 2>/dev/null && echo "[OK] 已按进程名停" || echo "[!] 没找到在跑的实例"
  fi
  exit 0
fi

# ---- 环境 ----
export HF_HUB_OFFLINE=1                 # 权重已缓存,离线加载,别联网重下
export CUDA_VISIBLE_DEVICES
# shellcheck disable=SC1091
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# ---- 已在跑就别重复起 ----
if curl -m 3 -s "http://$SERVE_HOST:$SERVE_PORT/v1/models" 2>/dev/null | grep -q "$SERVED_NAME"; then
  echo "[!] $SERVE_HOST:$SERVE_PORT 已有 $SERVED_NAME 在跑,无需重启。"; exit 0
fi

echo "[*] 启动 vLLM"
echo "    模型: $MODEL"
echo "    端点: http://$SERVE_HOST:$SERVE_PORT   served-name: $SERVED_NAME"
echo "    卡: GPU$CUDA_VISIBLE_DEVICES   显存占用上限: $GPU_UTIL   max-len: $MAXLEN"
echo "    日志: $LOG   环境: $ENV_NAME"

# 注:AWQ 量化 vLLM 会从模型 config 自动识别;想更快可加 --quantization awq_marlin(4090/Ada 支持)。
setsid nohup vllm serve "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --host "$SERVE_HOST" --port "$SERVE_PORT" \
  --max-model-len "$MAXLEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --dtype auto \
  > "$LOG" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
echo "[*] 已后台启动 PID $(cat "$PIDFILE")。首次加载权重约 1-3 分钟,等待就绪..."

# ---- 就绪探测 ----
for i in $(seq 1 60); do
  sleep 5
  if curl -m 3 -s "http://$SERVE_HOST:$SERVE_PORT/v1/models" 2>/dev/null | grep -q "$SERVED_NAME"; then
    echo "[OK] 就绪 ✅  http://$SERVE_HOST:$SERVE_PORT  (模型名 $SERVED_NAME)"
    curl -m 5 -s "http://$SERVE_HOST:$SERVE_PORT/v1/models"; echo
    echo "[提示] 停止用: bash start_qwen_vllm.sh stop"
    exit 0
  fi
  if grep -qiE "error while|Traceback|CUDA out of memory|Address already in use|ValueError" "$LOG" 2>/dev/null; then
    echo "[ERR] 日志疑似报错,末尾 25 行:"; tail -25 "$LOG"; exit 1
  fi
done
echo "[ERR] 5 分钟仍未就绪,看日志:$LOG"; tail -30 "$LOG"; exit 1

# ================= 备选弱检查器(改 MODEL 环境变量即可)=================
# 更弱(现象对比更明显): Qwen/Qwen2.5-Coder-1.5B
# 更强的"实习生":        Qwen/Qwen2.5-Coder-32B-Instruct-AWQ   (24GB 偏紧,建议 MAXLEN=8192 GPU_UTIL=0.92)
# 现代 MoE(快):          stelterlab/Qwen3-Coder-30B-A3B-Instruct-AWQ
