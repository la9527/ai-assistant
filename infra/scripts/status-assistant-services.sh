#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

echo "== launchd =="
launchctl list | grep 'com.aiassistant.llama-' || true
launchctl list | grep 'com.aiassistant.stack' || true

echo
echo "== llama.cpp endpoint =="
curl -fsS http://127.0.0.1:1242/v1/models >/dev/null && echo "1242 ok" || echo "1242 unavailable"

echo
echo "== docker compose =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps