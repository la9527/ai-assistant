#!/usr/bin/env zsh

set -euo pipefail

MODEL_NAME="${MLX_BASE_MODEL_NAME:-lmstudio-community/LFM2-24B-A2B-MLX-4bit}"
HOST="${MLX_BASE_SERVER_HOST:-0.0.0.0}"
PORT="${MLX_BASE_SERVER_PORT:-1235}"
LOG_LEVEL="${MLX_BASE_SERVER_LOG_LEVEL:-INFO}"

exec "$HOME/.local/bin/mlx_lm.server" \
  --model "$MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --log-level "$LOG_LEVEL"