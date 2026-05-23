#!/usr/bin/env zsh

set -euo pipefail

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
GUI_DOMAIN="gui/$TARGET_UID"
LOCAL_SCRIPT_DIR="$TARGET_HOME/.aiassistant-launchd-scripts"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

GUI_PLIST="$TARGET_HOME/Library/LaunchAgents/com.aiassistant.llama-lfm2-server.plist"
DAEMON_PLIST="/Library/LaunchDaemons/com.aiassistant.llama-lfm2-server.daemon.plist"

launchctl disable "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
if [[ -f "$GUI_PLIST" ]]; then
  launchctl bootout "$GUI_DOMAIN" "$GUI_PLIST" >/dev/null 2>&1 || true
  rm -f "$GUI_PLIST"
else
  launchctl bootout "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
fi

rm -f "$LOCAL_SCRIPT_DIR/start-llama-cpp-lfm2-server.sh"

if [[ $EUID -eq 0 ]]; then
  launchctl disable system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1 || true
  if [[ -f "$DAEMON_PLIST" ]]; then
    launchctl bootout system "$DAEMON_PLIST" >/dev/null 2>&1 || true
    rm -f "$DAEMON_PLIST"
  else
    launchctl bootout system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1 || true
  fi
else
  echo "System llama.cpp daemon was not removed. Re-run with sudo to remove boot-time daemon too."
fi