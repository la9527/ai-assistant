#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

if [[ $# -gt 0 ]]; then
  services=("$@")
else
  services=(proxy webui api worker n8n redis postgres)
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop "${services[@]}"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps