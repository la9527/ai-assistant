#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

echo "== launchd =="
launchctl list | grep 'com.aiassistant.mlx-' || true
launchctl list | grep 'com.aiassistant.stack' || true

echo
echo "== mlx endpoints =="
curl -fsS http://127.0.0.1:1235/v1/models >/dev/null && echo "1235 ok" || echo "1235 unavailable"
curl -fsS http://127.0.0.1:1236/v1/models >/dev/null && echo "1236 ok" || echo "1236 unavailable"

echo
echo "== docker compose =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps