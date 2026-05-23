#!/usr/bin/env zsh

set -euo pipefail

MODEL_REPO="${LLAMA_CPP_MODEL_REPO:-LiquidAI/LFM2-24B-A2B-GGUF:Q4_0}"
MODEL_FILE="${LLAMA_CPP_MODEL_FILE:-}"
MODEL_ALIAS="${LLAMA_CPP_MODEL_ALIAS:-LiquidAI/LFM2-24B-A2B-GGUF:Q4_0}"
HOST="${LLAMA_CPP_HOST:-0.0.0.0}"
PORT="${LLAMA_CPP_PORT:-1242}"
CTX_SIZE="${LLAMA_CPP_CTX_SIZE:-131072}"
PREDICT="${LLAMA_CPP_N_PREDICT:-8192}"
THREADS="${LLAMA_CPP_THREADS:-}"
BATCH_SIZE="${LLAMA_CPP_BATCH_SIZE:-}"
UBATCH_SIZE="${LLAMA_CPP_UBATCH_SIZE:-}"
GPU_LAYERS="${LLAMA_CPP_GPU_LAYERS:-auto}"
FLASH_ATTN="${LLAMA_CPP_FLASH_ATTN:-auto}"
AI_STORAGE_ROOT="${AI_STORAGE_ROOT:-/Volumes/ExtData/ai-assistant}"
LLAMA_CPP_ROOT="${LLAMA_CPP_ROOT:-$AI_STORAGE_ROOT/llama-cpp}"
HF_HOME="${HF_HOME:-$LLAMA_CPP_ROOT/huggingface}"
HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"

mkdir -p "$LLAMA_CPP_ROOT/models" "$HF_HOME" "$HUGGINGFACE_HUB_CACHE"

export AI_STORAGE_ROOT
export LLAMA_CPP_ROOT
export HF_HOME
export HUGGINGFACE_HUB_CACHE

resolve_llama_server_bin() {
  local candidates=(
    "/opt/homebrew/bin/llama-server"
    "/usr/local/bin/llama-server"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  command -v llama-server
}

LLAMA_SERVER_BIN="$(resolve_llama_server_bin)"

typeset -a SERVER_ARGS
SERVER_ARGS=(
  --hf-repo "$MODEL_REPO"
  --alias "$MODEL_ALIAS"
  --host "$HOST"
  --port "$PORT"
  --ctx-size "$CTX_SIZE"
  --n-predict "$PREDICT"
  --gpu-layers "$GPU_LAYERS"
  --flash-attn "$FLASH_ATTN"
)

[[ -n "$MODEL_FILE" ]] && SERVER_ARGS+=(--hf-file "$MODEL_FILE")
[[ -n "$THREADS" ]] && SERVER_ARGS+=(--threads "$THREADS")
[[ -n "$BATCH_SIZE" ]] && SERVER_ARGS+=(--batch-size "$BATCH_SIZE")
[[ -n "$UBATCH_SIZE" ]] && SERVER_ARGS+=(--ubatch-size "$UBATCH_SIZE")

exec "$LLAMA_SERVER_BIN" "${SERVER_ARGS[@]}"