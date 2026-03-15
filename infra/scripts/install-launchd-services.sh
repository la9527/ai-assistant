#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="$ROOT_DIR/infra/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"
GUI_DOMAIN="gui/$(id -u)"
plists=(
  com.aiassistant.mlx-base-server.plist
  com.aiassistant.mlx-webui-proxy.plist
  com.aiassistant.stack.plist
)

mkdir -p "$TARGET_DIR"

for plist_name in "${plists[@]}"; do
  src="$LAUNCHD_DIR/$plist_name"
  dst="$TARGET_DIR/$plist_name"
  cp "$src" "$dst"
  launchctl bootout "$GUI_DOMAIN" "$dst" >/dev/null 2>&1 || true
  launchctl bootstrap "$GUI_DOMAIN" "$dst"
done

launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.mlx-base-server"
launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.mlx-webui-proxy"
launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.stack"

launchctl list | grep 'com.aiassistant.mlx-' || true
launchctl list | grep 'com.aiassistant.stack' || true