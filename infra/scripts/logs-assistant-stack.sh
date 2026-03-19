#!/usr/bin/env zsh
# ---------------------------------------------------------------------------
# logs-assistant-stack.sh — AI Assistant 스택 실시간 로그 뷰어
#
# 사용법:
#   ./infra/scripts/logs-assistant-stack.sh          # 전체 서비스 로그
#   ./infra/scripts/logs-assistant-stack.sh api       # API만
#   ./infra/scripts/logs-assistant-stack.sh api webui # API + WebUI
#   ./infra/scripts/logs-assistant-stack.sh -n 100    # 최근 100줄부터
#   ./infra/scripts/logs-assistant-stack.sh --no-color api  # 색상 없이
# ---------------------------------------------------------------------------

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

TAIL_LINES=50
NO_COLOR=false
services=()

# 인자 파싱
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--tail)
      TAIL_LINES="$2"
      shift 2
      ;;
    --no-color)
      NO_COLOR=true
      shift
      ;;
    -h|--help)
      echo "사용법: $(basename "$0") [옵션] [서비스...]"
      echo ""
      echo "옵션:"
      echo "  -n, --tail N    최근 N줄부터 표시 (기본: 50)"
      echo "  --no-color      색상 없이 출력"
      echo "  -h, --help      도움말"
      echo ""
      echo "서비스: api, webui, postgres, redis, n8n, worker, proxy"
      echo "서비스를 지정하지 않으면 전체 서비스 로그를 표시합니다."
      exit 0
      ;;
    *)
      services+=("$1")
      shift
      ;;
  esac
done

compose_cmd=(docker compose -f "$COMPOSE_FILE")
[[ -f "$ENV_FILE" ]] && compose_cmd+=(--env-file "$ENV_FILE")

log_args=(--follow --tail "$TAIL_LINES" --timestamps)

if $NO_COLOR; then
  log_args+=(--no-color)
fi

echo "📋 AI Assistant 실시간 로그 (Ctrl+C로 종료)"
echo "   서비스: ${services[*]:-전체}"
echo "   최근 ${TAIL_LINES}줄부터 표시"
echo "---"

exec "${compose_cmd[@]}" logs "${log_args[@]}" "${services[@]}"
