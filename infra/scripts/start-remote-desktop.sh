#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
DOCKER_START_TIMEOUT_SECONDS="${DOCKER_START_TIMEOUT_SECONDS:-300}"
DOCKER_POLL_INTERVAL_SECONDS="${DOCKER_POLL_INTERVAL_SECONDS:-5}"

unset GUACAMOLE_USERNAME
unset GUACAMOLE_PASSWORD
unset GUACAMOLE_CONNECTION_NAME
unset GUACAMOLE_VNC_HOST
unset GUACAMOLE_VNC_PORT
unset GUACAMOLE_VNC_USERNAME
unset GUACAMOLE_VNC_USE_LOGIN_PASSWORD
unset GUACAMOLE_VNC_PASSWORD
unset GUACAMOLE_VNC_COLOR_DEPTH
unset GUACAMOLE_VNC_COMPRESS_LEVEL
unset GUACAMOLE_VNC_QUALITY_LEVEL
unset GUACAMOLE_VNC_DISABLE_DISPLAY_RESIZE
unset GUACAMOLE_VNC_ENABLE_AUDIO
unset GUACAMOLE_VNC_ENCODINGS
unset GUACD_LOG_LEVEL

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

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile remote-desktop up -d guacamole
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile remote-desktop ps