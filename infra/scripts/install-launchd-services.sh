#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="$ROOT_DIR/infra/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"
GUI_DOMAIN="gui/$(id -u)"
LOCAL_SCRIPT_DIR="$HOME/.aiassistant-launchd-scripts"

wait_for_endpoint() {
  local port="$1"
  local attempt

  for attempt in {1..20}; do
    if curl -fsS "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then
      echo "Endpoint $port ready"
      return 0
    fi

    sleep 1
  done

  echo "Endpoint $port did not become ready yet" >&2
  return 1
}

has_system_daemon() {
  [[ -f "/Library/LaunchDaemons/$1.daemon.plist" ]]
}

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
    com.aiassistant.llama-lfm2-server.plist)
      plist_set_string "$plist_path" ":ProgramArguments:0" "/bin/zsh"
      plist_set_string "$plist_path" ":ProgramArguments:1" "-lc"
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"
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

mkdir -p "$TARGET_DIR" "$LOCAL_SCRIPT_DIR"

launchctl disable "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
launchctl bootout "$GUI_DOMAIN" "$TARGET_DIR/com.aiassistant.llama-lfm2-server.plist" >/dev/null 2>&1 || true

cp "$ROOT_DIR/infra/scripts/start-llama-cpp-lfm2-server.sh" "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"
cp "$ROOT_DIR/infra/scripts/start-assistant-stack.sh" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"
chmod 755 "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"

managed_plists=(com.aiassistant.stack.plist)
if ! has_system_daemon com.aiassistant.llama-lfm2-server; then
  managed_plists+=(com.aiassistant.llama-lfm2-server.plist)
fi

for plist_name in "${managed_plists[@]}"; do
  local_src="$LAUNCHD_DIR/$plist_name"
  local_dst="$TARGET_DIR/$plist_name"
  label="${plist_name%.plist}"
  cp "$local_src" "$local_dst"
  rewrite_plist_for_current_layout "$plist_name" "$local_dst"
  launchctl enable "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl bootout "$GUI_DOMAIN" "$local_dst" >/dev/null 2>&1 || true
  launchctl bootstrap "$GUI_DOMAIN" "$local_dst"
done

launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.stack" >/dev/null 2>&1 || true

if has_system_daemon com.aiassistant.llama-lfm2-server; then
  echo "Skipping LaunchAgent install for com.aiassistant.llama-lfm2-server because the system daemon is installed."
else
  launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
  wait_for_endpoint 1242 || true
fi

launchctl list | grep 'com.aiassistant.llama-' || true
launchctl list | grep 'com.aiassistant.stack' || true