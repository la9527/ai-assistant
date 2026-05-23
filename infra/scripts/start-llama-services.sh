#!/usr/bin/env zsh

set -euo pipefail

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

GUI_DOMAIN="gui/$TARGET_UID"
GUI_PLIST="$TARGET_HOME/Library/LaunchAgents/com.aiassistant.llama-lfm2-server.plist"
DAEMON_PLIST="/Library/LaunchDaemons/com.aiassistant.llama-lfm2-server.daemon.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

wait_for_endpoint() {
  local attempt
  for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:1242/v1/models >/dev/null 2>&1; then
      echo "Endpoint 1242 ready"
      return 0
    fi
    sleep 1
  done
  echo "Endpoint 1242 did not become ready yet" >&2
  return 1
}

if [[ $EUID -eq 0 ]]; then
  if [[ ! -f "$DAEMON_PLIST" ]]; then
    "$SCRIPT_DIR/install-launchd-daemons.sh"
  fi
  launchctl enable system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1 || true
  launchctl bootout system "$DAEMON_PLIST" >/dev/null 2>&1 || true
  launchctl bootstrap system "$DAEMON_PLIST"
  launchctl kickstart -k system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1 || true
else
  if [[ -f "$DAEMON_PLIST" ]]; then
    echo "System llama.cpp daemon is installed. Re-run with sudo to manage it directly."
  elif [[ ! -f "$GUI_PLIST" ]]; then
    "$SCRIPT_DIR/install-launchd-services.sh"
  else
    launchctl enable "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
    launchctl bootout "$GUI_DOMAIN" "$GUI_PLIST" >/dev/null 2>&1 || true
    launchctl bootstrap "$GUI_DOMAIN" "$GUI_PLIST"
    launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
  fi
fi

wait_for_endpoint || true