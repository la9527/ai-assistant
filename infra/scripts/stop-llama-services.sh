#!/usr/bin/env zsh

set -euo pipefail

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
GUI_DOMAIN="gui/$TARGET_UID"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

GUI_PLIST="$TARGET_HOME/Library/LaunchAgents/com.aiassistant.llama-lfm2-server.plist"
DAEMON_PLIST="/Library/LaunchDaemons/com.aiassistant.llama-lfm2-server.daemon.plist"

if [[ -f "$GUI_PLIST" ]]; then
  launchctl bootout "$GUI_DOMAIN" "$GUI_PLIST" >/dev/null 2>&1 || true
else
  launchctl bootout "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1 || true
fi

if [[ $EUID -eq 0 ]]; then
  if [[ -f "$DAEMON_PLIST" ]]; then
    launchctl bootout system "$DAEMON_PLIST" >/dev/null 2>&1 || true
  else
    launchctl bootout system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1 || true
  fi
else
  echo "System llama.cpp daemon was not touched. Re-run with sudo to stop boot-time daemon as well."
fi