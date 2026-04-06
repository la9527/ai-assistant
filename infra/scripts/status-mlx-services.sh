#!/usr/bin/env zsh

set -euo pipefail

TARGET_MODE="${1:-default}"
TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
GUI_DOMAIN="gui/$TARGET_UID"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

case "$TARGET_MODE" in
  default)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    endpoint_specs=("1235 base" "1236 proxy")
    ;;
  gemma)
    gui_labels=(com.aiassistant.mlx-gemma-server)
    daemon_labels=(com.aiassistant.mlx-gemma-server.daemon)
    endpoint_specs=("1240 gemma")
    ;;
  all)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-gemma-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-gemma-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    endpoint_specs=("1235 base" "1240 gemma" "1236 proxy")
    ;;
  *)
    echo "Unknown target: $TARGET_MODE" >&2
    echo "Usage: $0 [default|gemma|all]" >&2
    exit 1
    ;;
esac

echo "== mlx target =="
echo "$TARGET_MODE"

echo
echo "== mlx target user =="
echo "$TARGET_USER ($TARGET_HOME)"

echo
echo "== mlx launchd agents =="
for label in "${gui_labels[@]}"; do
  plist_path="$TARGET_HOME/Library/LaunchAgents/$label.plist"
  if [[ ! -f "$plist_path" ]]; then
    echo "$label not installed"
  elif launchctl print "$GUI_DOMAIN/$label" >/dev/null 2>&1; then
    echo "$label loaded"
  else
    echo "$label not loaded"
  fi
done

echo
echo "== mlx launchd daemons =="
for label in "${daemon_labels[@]}"; do
  plist_path="/Library/LaunchDaemons/$label.plist"
  if [[ ! -f "$plist_path" ]]; then
    echo "$label not installed"
  elif launchctl print "system/$label" >/dev/null 2>&1; then
    echo "$label loaded"
  else
    echo "$label not loaded"
  fi
done

echo
echo "== mlx listeners =="
for spec in "${endpoint_specs[@]}"; do
  port="${spec%% *}"
  name="${spec#* }"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "$port $name listening"
  else
    echo "$port $name not-listening"
  fi
done

echo
echo "== mlx endpoints =="
for spec in "${endpoint_specs[@]}"; do
  port="${spec%% *}"
  name="${spec#* }"
  if curl -fsS "http://127.0.0.1:$port/v1/models" >/dev/null; then
    echo "$port $name ok"
  else
    echo "$port $name unavailable"
  fi
done