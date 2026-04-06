#!/usr/bin/env zsh

set -euo pipefail

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"

if [[ -z "$TARGET_HOME" ]]; then
  TARGET_HOME="/Users/$TARGET_USER"
fi

TARGET_MODE="${1:-default}"
shift 2>/dev/null || true

GUI_DOMAIN="gui/$TARGET_UID"
GUI_DIR="$TARGET_HOME/Library/LaunchAgents"
SYSTEM_DIR="/Library/LaunchDaemons"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

has_daemon_plist() {
  local label="$1"
  [[ -f "$SYSTEM_DIR/$label.plist" ]]
}

case "$TARGET_MODE" in
  default)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    endpoint_ports=(1235 1236)
    ;;
  gemma)
    gui_labels=(com.aiassistant.mlx-gemma-server)
    daemon_labels=(com.aiassistant.mlx-gemma-server.daemon)
    endpoint_ports=(1240)
    ;;
  all)
    gui_labels=(com.aiassistant.mlx-base-server com.aiassistant.mlx-gemma-server com.aiassistant.mlx-webui-proxy)
    daemon_labels=(com.aiassistant.mlx-base-server.daemon com.aiassistant.mlx-gemma-server.daemon com.aiassistant.mlx-webui-proxy.daemon)
    endpoint_ports=(1235 1240 1236)
    ;;
  *)
    echo "Unknown target: $TARGET_MODE" >&2
    echo "Usage: $0 [default|gemma|all]" >&2
    exit 1
    ;;
esac

start_gui_job() {
  local label="$1"
  local plist_path="$GUI_DIR/$label.plist"

  if [[ ! -f "$plist_path" ]]; then
    return 1
  fi

  launchctl enable "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl bootout "$GUI_DOMAIN" "$plist_path" >/dev/null 2>&1 || true
  launchctl bootstrap "$GUI_DOMAIN" "$plist_path"
  launchctl kickstart -k "$GUI_DOMAIN/$label" >/dev/null 2>&1 || true
}

start_daemon_job() {
  local label="$1"
  local plist_path="$SYSTEM_DIR/$label.plist"

  if [[ ! -f "$plist_path" ]]; then
    return 1
  fi

  launchctl enable "system/$label" >/dev/null 2>&1 || true
  launchctl bootout system "$plist_path" >/dev/null 2>&1 || true
  launchctl bootstrap system "$plist_path"
  launchctl kickstart -k "system/$label" >/dev/null 2>&1 || true
}

ensure_daemon_installed_if_needed() {
  case "$TARGET_MODE" in
    gemma)
      if [[ ! -f "$SYSTEM_DIR/com.aiassistant.mlx-gemma-server.daemon.plist" ]]; then
        echo "Gemma daemon is not installed. Installing it now..."
        "$SCRIPT_DIR/install-launchd-daemons.sh" --with-gemma
      fi
      ;;
    default|all)
      if [[ ! -f "$SYSTEM_DIR/com.aiassistant.mlx-base-server.daemon.plist" ]] || [[ ! -f "$SYSTEM_DIR/com.aiassistant.mlx-webui-proxy.daemon.plist" ]]; then
        echo "Default MLX daemons are not installed. Installing them now..."
        "$SCRIPT_DIR/install-launchd-daemons.sh"
      fi

      if [[ "$TARGET_MODE" == "all" ]] && [[ ! -f "$SYSTEM_DIR/com.aiassistant.mlx-gemma-server.daemon.plist" ]]; then
        echo "Gemma daemon is not installed. Installing it now..."
        "$SCRIPT_DIR/install-launchd-daemons.sh" --with-gemma
      fi
      ;;
  esac
}

ensure_agent_installed_if_needed() {
  case "$TARGET_MODE" in
    gemma)
      if has_daemon_plist com.aiassistant.mlx-gemma-server.daemon; then
        return
      fi

      if [[ ! -f "$GUI_DIR/com.aiassistant.mlx-gemma-server.plist" ]]; then
        echo "Gemma LaunchAgent is not installed. Installing it now..."
        "$SCRIPT_DIR/install-launchd-services.sh" --with-gemma
      fi
      ;;
    default|all)
      if [[ ! -f "$GUI_DIR/com.aiassistant.mlx-base-server.plist" ]] && ! has_daemon_plist com.aiassistant.mlx-base-server.daemon; then
        echo "Base LaunchAgent is not installed. Installing user-managed MLX services now..."
        "$SCRIPT_DIR/install-launchd-services.sh"
      elif [[ ! -f "$GUI_DIR/com.aiassistant.mlx-webui-proxy.plist" ]] && ! has_daemon_plist com.aiassistant.mlx-webui-proxy.daemon; then
        echo "Default MLX LaunchAgents are not installed. Installing them now..."
        "$SCRIPT_DIR/install-launchd-services.sh"
      fi

      if [[ "$TARGET_MODE" == "all" ]] && [[ ! -f "$GUI_DIR/com.aiassistant.mlx-gemma-server.plist" ]] && ! has_daemon_plist com.aiassistant.mlx-gemma-server.daemon; then
        echo "Gemma LaunchAgent is not installed. Installing it now..."
        "$SCRIPT_DIR/install-launchd-services.sh" --with-gemma
      fi
      ;;
  esac
}

filter_gui_labels_for_user_mode() {
  local label

  user_gui_labels=()
  daemon_backed_labels=()

  for label in "${gui_labels[@]}"; do
    if has_daemon_plist "$label.daemon"; then
      daemon_backed_labels+=("$label")
    else
      user_gui_labels+=("$label")
    fi
  done
}

wait_for_endpoints() {
  local port
  local attempt

  for port in "${endpoint_ports[@]}"; do
    for attempt in {1..15}; do
      if curl -fsS "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then
        echo "Endpoint $port ready"
        break
      fi

      if [[ $attempt -eq 15 ]]; then
        echo "Endpoint $port did not become ready yet" >&2
        break
      fi

      sleep 1
    done
  done
}

if [[ $EUID -eq 0 ]]; then
  ensure_daemon_installed_if_needed
  echo "Starting system MLX services: ${daemon_labels[*]}"
  for label in "${daemon_labels[@]}"; do
    if ! start_daemon_job "$label"; then
      echo "Skipping $label because its daemon plist is not installed." >&2
    fi
  done

  wait_for_endpoints
else
  filter_gui_labels_for_user_mode
  ensure_agent_installed_if_needed

  if (( ${#daemon_backed_labels[@]} > 0 )); then
    echo "Skipping daemon-managed MLX services in user mode: ${daemon_backed_labels[*]}"
  fi

  if (( ${#user_gui_labels[@]} == 0 )); then
    echo "No user-managed MLX services to start for target '$TARGET_MODE'."
  else
    echo "Starting user MLX services: ${user_gui_labels[*]}"
  fi

  for label in "${user_gui_labels[@]}"; do
    if ! start_gui_job "$label"; then
      echo "Skipping $label because its LaunchAgent plist is not installed." >&2
    fi
  done

  wait_for_endpoints

  echo "System MLX daemons were not touched. Re-run with sudo to manage boot-time daemons."
fi