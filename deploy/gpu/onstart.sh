#!/usr/bin/env bash
# Vast.ai "on-start script" for the GPU instance (PyTorch/CUDA template).
# Set in the instance env: TS_AUTHKEY (Tailscale auth key), optional MODELS.
# Everything persistent lives in /workspace (keep the instance's disk; only STOP, never DESTROY).
set -euo pipefail
export OLLAMA_MODELS=/workspace/ollama
export OLLAMA_HOST=127.0.0.1:11434   # reachable only through the Tailscale tunnel
export OLLAMA_KEEP_ALIVE=30m
MODELS="${MODELS:-qwen2.5-coder:14b qwen2.5-coder:7b qwen2.5:14b llama3.1:8b nomic-embed-text}"
mkdir -p "$OLLAMA_MODELS" /workspace/logs

# 1) Tailscale in userspace mode (Vast instances are containers without /dev/net/tun).
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! pgrep -x tailscaled >/dev/null; then
  nohup tailscaled --tun=userspace-networking --state=/workspace/tailscaled.state \
    >/workspace/logs/tailscaled.log 2>&1 &
  sleep 3
fi
tailscale up --authkey="${TS_AUTHKEY:?set TS_AUTHKEY}" --hostname=devagent-gpu || true

# 2) Ollama
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! pgrep -x ollama >/dev/null; then
  nohup ollama serve >/workspace/logs/ollama.log 2>&1 &
  sleep 5
fi
for m in $MODELS; do
  ollama pull "$m"
done

# 3) Training deps (only needed for the learning cycle)
pip install -q -r /workspace/agent/training/requirements.txt 2>/dev/null || true

echo "GPU box ready: $(tailscale ip -4 2>/dev/null | head -1):11434"
