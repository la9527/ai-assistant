#!/usr/bin/env zsh

set -euo pipefail

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
GUI_DOMAIN="gui/$TARGET_UID"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

echo "== llama target user =="
echo "$TARGET_USER ($TARGET_HOME)"

echo
echo "== llama launchd agent =="
if [[ ! -f "$TARGET_HOME/Library/LaunchAgents/com.aiassistant.llama-lfm2-server.plist" ]]; then
  echo "com.aiassistant.llama-lfm2-server not installed"
elif launchctl print "$GUI_DOMAIN/com.aiassistant.llama-lfm2-server" >/dev/null 2>&1; then
  echo "com.aiassistant.llama-lfm2-server loaded"
else
  echo "com.aiassistant.llama-lfm2-server not loaded"
fi

echo
echo "== llama launchd daemon =="
if [[ ! -f "/Library/LaunchDaemons/com.aiassistant.llama-lfm2-server.daemon.plist" ]]; then
  echo "com.aiassistant.llama-lfm2-server.daemon not installed"
elif launchctl print system/com.aiassistant.llama-lfm2-server.daemon >/dev/null 2>&1; then
  echo "com.aiassistant.llama-lfm2-server.daemon loaded"
else
  echo "com.aiassistant.llama-lfm2-server.daemon not loaded"
fi

echo
echo "== llama listener =="
if lsof -nP -iTCP:1242 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "1242 listening"
else
  echo "1242 not-listening"
fi

echo
echo "== llama endpoint =="
if curl -fsS http://127.0.0.1:1242/v1/models >/dev/null 2>&1; then
  echo "1242 ok"
else
  echo "1242 unavailable"
fi