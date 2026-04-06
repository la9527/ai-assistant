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
LOCAL_SCRIPT_DIR="$TARGET_HOME/.aiassistant-launchd-scripts"

TARGET_MODE="${1:-default}"

case "$TARGET_MODE" in
  default)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    remove_base_script=1
    remove_proxy_script=1
    ;;
  gemma)
    gui_labels=(com.aiassistant.mlx-gemma-server)
    daemon_labels=(com.aiassistant.mlx-gemma-server.daemon)
    remove_base_script=0
    remove_proxy_script=0
    ;;
  all)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-gemma-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-gemma-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    remove_base_script=1
    remove_proxy_script=1
    ;;
  *)
    echo "Unknown target: $TARGET_MODE" >&2
    echo "Usage: $0 [default|gemma|all]" >&2
    exit 1
    ;;
esac

remove_gui_job() {
  local label="$1"
  local plist_path="$TARGET_DIR/$label.plist"

  launchctl disable "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
  if [[ -f "$plist_path" ]]; then
    launchctl bootout "$GUI_DOMAIN" "$plist_path" >/dev/null 2>&1 || true
    rm -f "$plist_path"
  else
    launchctl bootout "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
  fi
}

remove_daemon_job() {
  local label="$1"
  local plist_path="/Library/LaunchDaemons/$label.plist"

  launchctl disable "system/$label" >/dev/null 2>&1 || true
  if [[ -f "$plist_path" ]]; then
    launchctl bootout system "$plist_path" >/dev/null 2>&1 || true
    rm -f "$plist_path"
  else
    launchctl bootout "system/$label" >/dev/null 2>&1 || true
  fi
}

echo "Removing user MLX launchd jobs for $TARGET_USER..."
for label in "${gui_labels[@]}"; do
  remove_gui_job "$label"
done

if [[ $remove_base_script -eq 1 ]]; then
  rm -f "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
fi

if [[ $remove_proxy_script -eq 1 ]]; then
  rm -f "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
fi

if [[ $EUID -eq 0 ]]; then
  echo "Removing system MLX launchd daemons..."
  for label in "${daemon_labels[@]}"; do
    remove_daemon_job "$label"
  done
else
  echo "System MLX daemons were not removed. Re-run with sudo to remove boot-time daemons too."
  echo "Example: sudo $0"
fi

echo
echo "Remaining MLX plist files:"
if find "$TARGET_DIR" -maxdepth 1 -name 'com.aiassistant.mlx*.plist' -print -quit | grep -q .; then
  find "$TARGET_DIR" -maxdepth 1 -name 'com.aiassistant.mlx*.plist' -print | sort
else
  echo "no user mlx plists"
fi
if [[ $EUID -eq 0 ]]; then
  if find /Library/LaunchDaemons -maxdepth 1 -name 'com.aiassistant.mlx*.plist' -print -quit | grep -q .; then
    find /Library/LaunchDaemons -maxdepth 1 -name 'com.aiassistant.mlx*.plist' -print | sort
  else
    echo "no system mlx plists"
  fi
fi