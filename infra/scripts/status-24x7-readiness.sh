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
echo "== mlx launchd agents =="
launchctl list | grep 'com.aiassistant.mlx-' || echo "no active mlx gui agents"

echo
echo "== mlx launchd agent disabled flags =="
launchctl print-disabled "gui/$(id -u)" 2>/dev/null | grep 'com.aiassistant.mlx-' || echo "no disabled mlx gui jobs"

echo
echo "== mlx launchd daemons =="
launchctl print system/com.aiassistant.mlx-base-server.daemon >/dev/null 2>&1 && echo "mlx base daemon loaded" || echo "mlx base daemon not loaded"
launchctl print system/com.aiassistant.mlx-webui-proxy.daemon >/dev/null 2>&1 && echo "mlx webui proxy daemon loaded" || echo "mlx webui proxy daemon not loaded"

echo
echo "== docker compose =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

echo
echo "== mlx endpoints =="
curl -fsS http://127.0.0.1:1235/v1/models >/dev/null && echo "1235 ok" || echo "1235 unavailable"
curl -fsS http://127.0.0.1:1236/v1/models >/dev/null && echo "1236 ok" || echo "1236 unavailable"