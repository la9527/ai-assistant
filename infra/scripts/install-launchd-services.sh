#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="$ROOT_DIR/infra/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"
GUI_DOMAIN="gui/$(id -u)"
LOCAL_SCRIPT_DIR="$HOME/.aiassistant-launchd-scripts"
INSTALL_GEMMA=0

if [[ "${1:-}" == "--with-gemma" ]]; then
  INSTALL_GEMMA=1
fi

wait_for_endpoints() {
  local port
  local attempt

  for port in "$@"; do
    for attempt in {1..20}; do
      if curl -fsS "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then
        echo "Endpoint $port ready"
        break
      fi

      if [[ $attempt -eq 20 ]]; then
        echo "Endpoint $port did not become ready yet" >&2
        break
      fi

      sleep 1
    done
  done
}

has_system_daemon() {
  local label="$1"
  [[ -f "/Library/LaunchDaemons/$label.daemon.plist" ]]
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
    com.aiassistant.mlx-base-server.plist)
      plist_set_string "$plist_path" ":ProgramArguments:0" "/bin/zsh"
      plist_set_string "$plist_path" ":ProgramArguments:1" "-lc"
      plist_set_string "$plist_path" ":ProgramArguments:2" "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
      ;;
    com.aiassistant.mlx-gemma-server.plist)
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

if [[ $INSTALL_GEMMA -eq 1 ]]; then
  plists+=(com.aiassistant.mlx-gemma-server.plist)
fi

endpoint_ports=()

managed_plists=(com.aiassistant.stack.plist)

if ! has_system_daemon com.aiassistant.mlx-base-server; then
  managed_plists+=(com.aiassistant.mlx-base-server.plist)
  endpoint_ports+=(1235)
fi

if ! has_system_daemon com.aiassistant.mlx-webui-proxy; then
  managed_plists+=(com.aiassistant.mlx-webui-proxy.plist)
  endpoint_ports+=(1236)
fi

if [[ $INSTALL_GEMMA -eq 1 ]] && ! has_system_daemon com.aiassistant.mlx-gemma-server; then
  managed_plists+=(com.aiassistant.mlx-gemma-server.plist)
  endpoint_ports+=(1240)
fi

for plist_name in com.aiassistant.mlx-base-server.plist com.aiassistant.mlx-gemma-server.plist com.aiassistant.mlx-webui-proxy.plist; do
  label="${plist_name%.plist}"
  dst="$TARGET_DIR/$plist_name"

  case "$label" in
    com.aiassistant.mlx-base-server)
      daemon_managed=$(has_system_daemon "$label" && echo 1 || echo 0)
      ;;
    com.aiassistant.mlx-gemma-server)
      daemon_managed=$(has_system_daemon "$label" && echo 1 || echo 0)
      ;;
    com.aiassistant.mlx-webui-proxy)
      daemon_managed=$(has_system_daemon "$label" && echo 1 || echo 0)
      ;;
  esac

  if [[ "$plist_name" == "com.aiassistant.mlx-gemma-server.plist" ]] && [[ $INSTALL_GEMMA -eq 0 ]]; then
    daemon_managed=1
  fi

  if [[ $daemon_managed -eq 1 ]]; then
    launchctl disable "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
    if [[ -f "$dst" ]]; then
      launchctl bootout "$GUI_DOMAIN" "$dst" >/dev/null 2>&1 || true
      rm -f "$dst"
    fi
  fi
done

mkdir -p "$TARGET_DIR"
mkdir -p "$LOCAL_SCRIPT_DIR"

cp "$ROOT_DIR/infra/scripts/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh"
cp "$ROOT_DIR/infra/scripts/start-mlx-webui-proxy.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh"
cp "$ROOT_DIR/infra/scripts/start-assistant-stack.sh" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"
chmod 755 "$LOCAL_SCRIPT_DIR/start-mlx-base-server.sh" "$LOCAL_SCRIPT_DIR/start-mlx-webui-proxy.sh" "$LOCAL_SCRIPT_DIR/start-assistant-stack.sh"

for plist_name in "${managed_plists[@]}"; do
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

if [[ $INSTALL_GEMMA -eq 1 ]] && ! has_system_daemon com.aiassistant.mlx-gemma-server; then
  launchctl kickstart -k "$GUI_DOMAIN/com.aiassistant.mlx-gemma-server" >/dev/null 2>&1 || true
else
  launchctl disable "$GUI_DOMAIN/com.aiassistant.mlx-gemma-server" >/dev/null 2>&1 || true
  launchctl bootout "$GUI_DOMAIN" "$TARGET_DIR/com.aiassistant.mlx-gemma-server.plist" >/dev/null 2>&1 || true
fi

if has_system_daemon com.aiassistant.mlx-base-server; then
  echo "Skipping LaunchAgent install for com.aiassistant.mlx-base-server because the system daemon is installed."
fi

if has_system_daemon com.aiassistant.mlx-webui-proxy; then
  echo "Skipping LaunchAgent install for com.aiassistant.mlx-webui-proxy because the system daemon is installed."
fi

if [[ $INSTALL_GEMMA -eq 1 ]] && has_system_daemon com.aiassistant.mlx-gemma-server; then
  echo "Skipping LaunchAgent install for com.aiassistant.mlx-gemma-server because the system daemon is installed."
fi

if (( ${#endpoint_ports[@]} > 0 )); then
  wait_for_endpoints "${endpoint_ports[@]}"
fi

launchctl list | grep 'com.aiassistant.mlx-' || true
launchctl list | grep 'com.aiassistant.stack' || true