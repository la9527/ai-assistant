#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
AI_STORAGE_ROOT="${AI_STORAGE_ROOT:-/Volumes/ExtData/ai-assistant}"
DOCKER_START_TIMEOUT_SECONDS="${DOCKER_START_TIMEOUT_SECONDS:-300}"
DOCKER_POLL_INTERVAL_SECONDS="${DOCKER_POLL_INTERVAL_SECONDS:-5}"

mkdir -p \
  "$AI_STORAGE_ROOT/docker/caddy/data" \
  "$AI_STORAGE_ROOT/docker/caddy/config" \
  "$AI_STORAGE_ROOT/docker/openwebui" \
  "$AI_STORAGE_ROOT/docker/n8n" \
  "$AI_STORAGE_ROOT/docker/postgres" \
  "$AI_STORAGE_ROOT/docker/redis" \
  "$AI_STORAGE_ROOT/docker/guacamole" \
  "$AI_STORAGE_ROOT/mlx/huggingface" \
  "$AI_STORAGE_ROOT/mlx/lmstudio"

export AI_STORAGE_ROOT

if [[ $# -gt 0 ]]; then
  services=("$@")
else
  services=(postgres redis n8n api worker webui proxy)
fi

compose_cmd=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

if [[ "${AI_ASSISTANT_ENABLE_AUTOMATION_PROFILE:-false}" == "true" ]]; then
  compose_cmd+=(--profile automation)
fi

if [[ "${AI_ASSISTANT_ENABLE_EDGE_PROFILE:-false}" == "true" ]]; then
  compose_cmd+=(--profile edge)
fi

waited_seconds=0

if ! docker info >/dev/null 2>&1; then
  open -a Docker
fi

until docker info >/dev/null 2>&1; do
  if (( waited_seconds >= DOCKER_START_TIMEOUT_SECONDS )); then
    echo "Docker Desktop did not become ready within ${DOCKER_START_TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  sleep "$DOCKER_POLL_INTERVAL_SECONDS"
  waited_seconds=$(( waited_seconds + DOCKER_POLL_INTERVAL_SECONDS ))
done

"${compose_cmd[@]}" up -d --build "${services[@]}"
"${compose_cmd[@]}" ps