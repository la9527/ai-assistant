#!/usr/bin/env zsh

set -euo pipefail

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

GUI_DOMAIN="gui/$TARGET_UID"
TARGET_DIR="$TARGET_HOME/Library/LaunchAgents"

TARGET_MODE="${1:-default}"

case "$TARGET_MODE" in
  default)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    ;;
  gemma)
    gui_labels=(com.aiassistant.mlx-gemma-server)
    daemon_labels=(com.aiassistant.mlx-gemma-server.daemon)
    ;;
  all)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-gemma-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-gemma-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    ;;
  *)
    echo "Unknown target: $TARGET_MODE" >&2
    echo "Usage: $0 [default|gemma|all]" >&2
    exit 1
    ;;
esac

stop_gui_job() {
  local label="$1"
  local plist_path="$TARGET_DIR/$label.plist"

  if [[ -f "$plist_path" ]]; then
    launchctl bootout "$GUI_DOMAIN" "$plist_path" >/dev/null 2>&1 || true
  else
    launchctl bootout "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
  fi
}

stop_daemon_job() {
  local label="$1"
  local plist_path="/Library/LaunchDaemons/$label.plist"

  if [[ -f "$plist_path" ]]; then
    launchctl bootout system "$plist_path" >/dev/null 2>&1 || true
  else
    launchctl bootout "system/$label" >/dev/null 2>&1 || true
  fi
}

echo "Stopping user MLX launchd jobs for $TARGET_USER..."
for label in "${gui_labels[@]}"; do
  stop_gui_job "$label"
done

if [[ $EUID -eq 0 ]]; then
  echo "Stopping system MLX launchd daemons..."
  for label in "${daemon_labels[@]}"; do
    stop_daemon_job "$label"
  done
else
  echo "System MLX daemons were not touched. Re-run with sudo to stop boot-time daemons as well."
  echo "Example: sudo $0"
fi

echo
echo "Remaining MLX jobs:"
launchctl list | grep 'com.aiassistant.mlx-' || echo "no active mlx gui jobs"
if [[ $EUID -eq 0 ]]; then
  launchctl print system/com.aiassistant.mlx-base-server.daemon >/dev/null 2>&1 && echo "mlx base daemon still loaded" || true
  launchctl print system/com.aiassistant.mlx-gemma-server.daemon >/dev/null 2>&1 && echo "mlx gemma daemon still loaded" || true
  launchctl print system/com.aiassistant.mlx-webui-proxy.daemon >/dev/null 2>&1 && echo "mlx webui proxy daemon still loaded" || true
fi