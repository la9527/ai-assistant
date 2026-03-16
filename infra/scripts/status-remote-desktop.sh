#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

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

echo "== remote-desktop compose =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile remote-desktop ps

echo
echo "== guacamole mapping =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile remote-desktop exec -T guacamole sh -lc 'sed -n "1,120p" /etc/guacamole/user-mapping.xml' || true