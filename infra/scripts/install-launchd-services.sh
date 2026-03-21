#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="$ROOT_DIR/infra/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"
GUI_DOMAIN="gui/$(id -u)"
LOCAL_SCRIPT_DIR="$HOME/.aiassistant-launchd-scripts"

plist_set_string() {
  local plist_path="$1"
  local key_path="$2"
  local value="$3"

  /usr/libexec/PlistBuddy -c "Set $key_path $value" "$plist_path" >/dev/null 2>&1 || \
    /usr/libexec/PlistBuddy -c "Add $key_path string $value" "$plist_path"
}

rewrite_plist_for_current_layout() {
  local plist_name="$1"
  local plist_path="$2"

  case "$plist_name" in
    com.aiassistant.mlx-base-server.plist)
      plist_set_string "$plist_path" ":ProgramArguments:0" "/bin/zsh"
      plist_set_string "$plist_path" ":ProgramArguments:1" "-lc"
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
      ;;
    com.aiassistant.mlx-webui-proxy.plist)
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
      ;;
    com.aiassistant.stack.plist)
      plist_set_string "$plist_path" ":ProgramArguments:0" "/bin/zsh"
      plist_set_string "$plist_path" ":ProgramArguments:1" "-lc"
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"
      ;;
  esac

  plist_set_string "$plist_path" ":WorkingDirectory" "$ROOT_DIR"
  plist_set_string "$plist_path" ":EnvironmentVariables:HOME" "$HOME"
  plist_set_string "$plist_path" ":EnvironmentVariables:PATH" "$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  plist_set_string "$plist_path" ":EnvironmentVariables:AI_ASSISTANT_ROOT_DIR" "$ROOT_DIR"
}

plists=(
  com.aiassistant.mlx-base-server.plist
  com.aiassistant.mlx-webui-proxy.plist
  com.aiassistant.stack.plist
)

if [[ -f /Library/LaunchDaemons/com.aiassistant.mlx-base-server.daemon.plist ]] || \
   [[ -f /Library/LaunchDaemons/com.aiassistant.mlx-webui-proxy.daemon.plist ]]; then
  plists=(com.aiassistant.stack.plist)

  for plist_name in com.aiassistant.mlx-base-server.plist com.aiassistant.mlx-webui-proxy.plist; do
    label="${plist_name%.plist}"
    dst="$TARGET_DIR/$plist_name"
    launchctl disable "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
    if [[ -f "$dst" ]]; then
      launchctl bootout "$GUI_DOMAIN" "$dst" >/dev/null 2>&1 || true
      rm -f "$dst"
    fi
  done
fi

mkdir -p "$TARGET_DIR"
mkdir -p "$LOCAL_SCRIPT_DIR"

cp "$ROOT_DIR/infra/scripts/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
cp "$ROOT_DIR/infra/scripts/start-mlx-webui-proxy.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
cp "$ROOT_DIR/infra/scripts/start-assistant-stack.sh" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"
chmod 755 "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"

for plist_name in "${plists[@]}"; do
  label="${plist_name%.plist}"
  src="$LAUNCHD_DIR/$plist_name"
  dst="$TARGET_DIR/$plist_name"
  cp "$src" "$dst"
  rewrite_plist_for_current_layout "$plist_name" "$dst"
  launchctl enable "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl bootout "$GUI_DOMAIN" "$dst" >/dev/null 2>&1 || true
  launchctl bootstrap "$GUI_DOMAIN" "$dst"
done

launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.mlx-base-server" >/dev/null 2>&1 || true
launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.mlx-webui-proxy" >/dev/null 2>&1 || true
launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.stack" >/dev/null 2>&1 || true

launchctl list | grep 'com.aiassistant.mlx-' || true
launchctl list | grep 'com.aiassistant.stack' || true