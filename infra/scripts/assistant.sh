#!/bin/zsh
set -euo pipefail
# ─────────────────────────────────────────────────────────────
# assistant.sh — AI Assistant 통합 관리 스크립트
# 사용법: assistant <그룹> <동작> [옵션]
# ─────────────────────────────────────────────────────────────

# Homebrew PATH 보장 (launchd 등 최소 환경에서도 동작)
if [[ ":$PATH:" != *":/opt/homebrew/bin:"* ]]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── 색상 ──────────────────────────────────────────────────────
_c_reset="\033[0m"
_c_bold="\033[1m"
_c_cyan="\033[36m"
_c_green="\033[32m"
_c_yellow="\033[33m"
_c_red="\033[31m"

_header()  { printf "${_c_bold}${_c_cyan}▸ %s${_c_reset}\n" "$*"; }
_ok()      { printf "${_c_green}  ✔ %s${_c_reset}\n" "$*"; }
_warn()    { printf "${_c_yellow}  ⚠ %s${_c_reset}\n" "$*"; }
_err()     { printf "${_c_red}  ✖ %s${_c_reset}\n" "$*" >&2; }

# ── 도움말 ────────────────────────────────────────────────────
show_help() {
  cat <<'EOF'

  AI Assistant 통합 관리 스크립트

  사용법: assistant <그룹> <동작> [옵션]

  ┌─────────────┬───────────────────┬──────────────────────────────┐
  │   그룹      │   동작            │   설명                       │
  ├─────────────┼───────────────────┼──────────────────────────────┤
  │ stack       │ start [서비스...] │ Docker Compose 스택 시작     │
  │             │ stop  [서비스...] │ Docker Compose 스택 중지     │
  │             │ status            │ 서비스 상태 확인             │
  │             │ logs  [옵션]      │ 실시간 로그 보기             │
  ├─────────────┼───────────────────┼──────────────────────────────┤
  │ mlx         │ start             │ MLX base 서버 시작           │
  │             │ start-proxy       │ MLX WebUI 프록시 시작        │
  ├─────────────┼───────────────────┼──────────────────────────────┤
  │ remote      │ start             │ Guacamole 원격 데스크톱 시작 │
  │             │ stop              │ Guacamole 중지               │
  │             │ status            │ Guacamole 상태 확인          │
  │             │ render            │ user-mapping.xml 생성        │
  ├─────────────┼───────────────────┼──────────────────────────────┤
  │ tailscale   │ start [포트]      │ Tailscale serve 시작         │
  │             │ stop              │ Tailscale serve 중지         │
  │             │ status            │ Tailscale serve 상태         │
  ├─────────────┼───────────────────┼──────────────────────────────┤
  │ launchd     │ install           │ LaunchAgent 서비스 설치      │
  │             │ install-daemon    │ LaunchDaemon 설치 (sudo)     │
  ├─────────────┼───────────────────┼──────────────────────────────┤
  │ readiness   │                   │ 24×7 운영 준비 상태 점검     │
  │ help        │                   │ 이 도움말 표시               │
  └─────────────┴───────────────────┴──────────────────────────────┘

  예시:
    assistant stack start                  # 전체 스택 시작
    assistant stack stop api               # api 서비스만 중지
    assistant stack logs -n 100 api        # api 로그 100줄
    assistant mlx start                    # MLX 서버 시작
    assistant remote start                 # 원격 데스크톱 시작
    assistant tailscale start 443          # Tailscale serve 포트 443
    assistant launchd install              # LaunchAgent 설치
    assistant readiness                    # 24×7 점검

EOF
}

# ── 스크립트 위임 실행 ────────────────────────────────────────
_run() {
  local script="$1"; shift
  local target="$SCRIPT_DIR/$script"
  if [[ ! -x "$target" ]]; then
    _err "스크립트 없음: $target"
    return 1
  fi
  "$target" "$@"
}

# ── stack ─────────────────────────────────────────────────────
cmd_stack() {
  local action="${1:-help}"; shift 2>/dev/null || true
  case "$action" in
    start)  _run start-assistant-stack.sh "$@" ;;
    stop)   _run stop-assistant-stack.sh "$@" ;;
    status) _run status-assistant-services.sh "$@" ;;
    logs)   _run logs-assistant-stack.sh "$@" ;;
    *)
      _err "stack: 알 수 없는 동작 '$action'"
      printf "  사용 가능: start, stop, status, logs\n"
      return 1
      ;;
  esac
}

# ── mlx ───────────────────────────────────────────────────────
cmd_mlx() {
  local action="${1:-help}"; shift 2>/dev/null || true
  case "$action" in
    start)       _run start-mlx-base-server.sh "$@" ;;
    start-proxy) _run start-mlx-webui-proxy.sh "$@" ;;
    *)
      _err "mlx: 알 수 없는 동작 '$action'"
      printf "  사용 가능: start, start-proxy\n"
      return 1
      ;;
  esac
}

# ── remote ────────────────────────────────────────────────────
cmd_remote() {
  local action="${1:-help}"; shift 2>/dev/null || true
  case "$action" in
    start)  _run start-remote-desktop.sh "$@" ;;
    stop)   _run stop-remote-desktop.sh "$@" ;;
    status) _run status-remote-desktop.sh "$@" ;;
    render) _run render-guacamole-user-mapping.sh "$@" ;;
    *)
      _err "remote: 알 수 없는 동작 '$action'"
      printf "  사용 가능: start, stop, status, render\n"
      return 1
      ;;
  esac
}

# ── tailscale ─────────────────────────────────────────────────
cmd_tailscale() {
  local action="${1:-help}"; shift 2>/dev/null || true
  case "$action" in
    start)  _run start-tailscale-serve.sh "$@" ;;
    stop)   _run stop-tailscale-serve.sh "$@" ;;
    status) _run status-tailscale-serve.sh "$@" ;;
    *)
      _err "tailscale: 알 수 없는 동작 '$action'"
      printf "  사용 가능: start, stop, status\n"
      return 1
      ;;
  esac
}

# ── launchd ───────────────────────────────────────────────────
cmd_launchd() {
  local action="${1:-help}"; shift 2>/dev/null || true
  case "$action" in
    install)        _run install-launchd-services.sh "$@" ;;
    install-daemon) _run install-launchd-daemons.sh "$@" ;;
    *)
      _err "launchd: 알 수 없는 동작 '$action'"
      printf "  사용 가능: install, install-daemon\n"
      return 1
      ;;
  esac
}

# ── readiness ─────────────────────────────────────────────────
cmd_readiness() {
  _run status-24x7-readiness.sh "$@"
}

# ── 메인 디스패치 ─────────────────────────────────────────────
main() {
  local group="${1:-help}"; shift 2>/dev/null || true
  case "$group" in
    stack)     cmd_stack "$@" ;;
    mlx)       cmd_mlx "$@" ;;
    remote)    cmd_remote "$@" ;;
    tailscale) cmd_tailscale "$@" ;;
    launchd)   cmd_launchd "$@" ;;
    readiness) cmd_readiness "$@" ;;
    help|-h|--help) show_help ;;
    *)
      _err "알 수 없는 그룹: '$group'"
      show_help
      return 1
      ;;
  esac
}

main "$@"
