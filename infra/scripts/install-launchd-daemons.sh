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

plist_set_string() {
  local plist_path="$1"
  local key_path="$2"
  local value="$3"

  /usr/libexec/PlistBuddy -c "Set $key_path $value" "$plist_path" >/dev/null 2>&1 || \
    /usr/libexec/PlistBuddy -c "Add $key_path string $value" "$plist_path"
}

rewrite_daemon_plist_for_current_layout() {
  local plist_path="$1"

  plist_set_string "$plist_path" ":ProgramArguments:0" "/bin/zsh"
  plist_set_string "$plist_path" ":ProgramArguments:1" "-lc"
  plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"
  plist_set_string "$plist_path" ":UserName" "$TARGET_USER"
  plist_set_string "$plist_path" ":WorkingDirectory" "$ROOT_DIR"
  plist_set_string "$plist_path" ":EnvironmentVariables:HOME" "$TARGET_HOME"
  plist_set_string "$plist_path" ":EnvironmentVariables:PATH" "$TARGET_HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  plist_set_string "$plist_path" ":EnvironmentVariables:AI_ASSISTANT_ROOT_DIR" "$ROOT_DIR"
}

mkdir -p "$TARGET_DIR" "$LOCAL_SCRIPT_DIR"
cp "$ROOT_DIR/infra/scripts/start-llama-cpp-lfm2-server.sh" "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"
chown "$TARGET_USER":staff "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"
chmod 755 "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"

launchctl disable "gui/$TARGET_UID/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
launchctl bootout "gui/$TARGET_UID/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
if [[ -f "$TARGET_HOME/Library/LaunchAgents/com.aiassistant.llama-lfm2-server.plist" ]]; then
  launchctl bootout "gui/$TARGET_UID" "$TARGET_HOME/Library/LaunchAgents/com.aiassistant.llama-lfm2-server.plist" >/dev/null 2>&1 || true
fi

src="$LAUNCHD_DIR/com.aiassistant.llama-lfm2-server.daemon.plist"
dst="$TARGET_DIR/com.aiassistant.llama-lfm2-server.daemon.plist"
cp "$src" "$dst"
rewrite_daemon_plist_for_current_layout "$dst"
chown root:wheel "$dst"
chmod 644 "$dst"
launchctl enable "system/com.aiassistant.llama-lfm2-server.daemon" >/dev/null 2>&1 || true
launchctl bootout system "$dst" >/dev/null 2>&1 || true
launchctl bootstrap system "$dst"
launchctl kickstart -k system/com.aiassistant.llama-lfm2-server.daemon
launchctl print system/com.aiassistant.llama-lfm2-server.daemon >/dev/null
wait_for_endpoint 1242 || true

echo "Installed llama.cpp LaunchDaemon for boot-time operation."
echo "Disabled user LaunchAgent for llama.cpp to prevent duplicate startup after autologin."
echo "Docker Compose core stack remains a LaunchAgent because Docker Desktop still requires a logged-in GUI session."