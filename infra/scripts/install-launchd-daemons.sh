#!/usr/bin/env zsh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="$ROOT_DIR/infra/launchd"
TARGET_DIR="/Library/LaunchDaemons"
TARGET_USER="${SUDO_USER:-byoungyoungla}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

LOCAL_SCRIPT_DIR="$TARGET_HOME/.aiassistant-launchd-scripts"

plist_set_string() {
  local plist_path="$1"
  local key_path="$2"
  local value="$3"

  /usr/libexec/PlistBuddy -c "Set $key_path $value" "$plist_path" >/dev/null 2>&1 || \
    /usr/libexec/PlistBuddy -c "Add $key_path string $value" "$plist_path"
}

rewrite_daemon_plist_for_current_layout() {
  local plist_name="$1"
  local plist_path="$2"

  case "$plist_name" in
    com.aiassistant.mlx-base-server.daemon.plist)
      plist_set_string "$plist_path" ":ProgramArguments:0" "/bin/zsh"
      plist_set_string "$plist_path" ":ProgramArguments:1" "-lc"
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
      ;;
    com.aiassistant.mlx-webui-proxy.daemon.plist)
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
      ;;
  esac

  plist_set_string "$plist_path" ":UserName" "$TARGET_USER"
  plist_set_string "$plist_path" ":WorkingDirectory" "$ROOT_DIR"
  plist_set_string "$plist_path" ":EnvironmentVariables:HOME" "$TARGET_HOME"
  plist_set_string "$plist_path" ":EnvironmentVariables:PATH" "$TARGET_HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  plist_set_string "$plist_path" ":EnvironmentVariables:AI_ASSISTANT_ROOT_DIR" "$ROOT_DIR"
}

daemon_plists=(
  com.aiassistant.mlx-base-server.daemon.plist
  com.aiassistant.mlx-webui-proxy.daemon.plist
)

gui_plists=(
  com.aiassistant.mlx-base-server.plist
  com.aiassistant.mlx-webui-proxy.plist
)

mkdir -p "$TARGET_DIR"
mkdir -p "$LOCAL_SCRIPT_DIR"
cp "$ROOT_DIR/infra/scripts/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
cp "$ROOT_DIR/infra/scripts/start-mlx-webui-proxy.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
chown "$TARGET_USER":staff "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
chmod 755 "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"

for plist_name in "${gui_plists[@]}"; do
  label="${plist_name%.plist}"
  gui_path="$TARGET_HOME/Library/LaunchAgents/$plist_name"
  launchctl disable "gui/$TARGET_UID/$label" >/dev/null 2>&1 || true
  launchctl bootout "gui/$TARGET_UID/$label" >/dev/null 2>&1 || true
  if [[ -f "$gui_path" ]]; then
    launchctl bootout "gui/$TARGET_UID" "$gui_path" >/dev/null 2>&1 || true
  fi
done

for plist_name in "${daemon_plists[@]}"; do
  src="$LAUNCHD_DIR/$plist_name"
  dst="$TARGET_DIR/$plist_name"
  cp "$src" "$dst"
  rewrite_daemon_plist_for_current_layout "$plist_name" "$dst"
  chown root:wheel "$dst"
  chmod 644 "$dst"
  launchctl bootout system "$dst" >/dev/null 2>&1 || true
  launchctl bootstrap system "$dst"
done

launchctl kickstart -k system/com.aiassistant.mlx-base-server.daemon
launchctl kickstart -k system/com.aiassistant.mlx-webui-proxy.daemon

launchctl print system/com.aiassistant.mlx-base-server.daemon >/dev/null
launchctl print system/com.aiassistant.mlx-webui-proxy.daemon >/dev/null

echo "Installed MLX LaunchDaemons for boot-time operation."
echo "Disabled user LaunchAgents for MLX to prevent duplicate startup after autologin."
echo "Docker Compose core stack remains a LaunchAgent because Docker Desktop still requires a logged-in GUI session."