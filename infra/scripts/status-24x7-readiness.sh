#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

echo "== power =="
pmset -g custom

echo
echo "== tailscale =="
tailscale status || true

echo
echo "== tailscale serve =="
tailscale serve status || true

echo
echo "== llama launchd agents =="
launchctl list | grep 'com.aiassistant.llama-' || echo "no active llama gui agents"

echo
echo "== llama launchd agent disabled flags =="
launchctl print-disabled "gui/$(id -u)" 2>/dev/null | grep 'com.aiassistant.llama-' || echo "no disabled llama gui jobs"

echo
echo "== llama launchd daemons =="
launchctl print system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1 && echo "llama daemon loaded" || echo "llama daemon not loaded"

echo
echo "== docker compose =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

echo
echo "== llama endpoint =="
curl -fsS http://127.0.0.1:1242/v1/models >/dev/null && echo "1242 ok" || echo "1242 unavailable"