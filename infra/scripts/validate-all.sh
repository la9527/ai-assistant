#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TEST_ENV_FILE="$ROOT_DIR/.env.test"
PYTHON_BIN="$ROOT_DIR/apps/api/.venv/bin/python"

if [[ ! -f "$TEST_ENV_FILE" ]]; then
  echo "Missing test env file: $TEST_ENV_FILE" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing python executable: $PYTHON_BIN" >&2
  exit 1
fi

set -a
source "$TEST_ENV_FILE"
set +a

cd "$ROOT_DIR"

echo "[1/4] Running API unit/integration tests"
"$PYTHON_BIN" -m pytest apps/api/tests apps/api/app/tests -q

echo "[2/4] Checking Docker service status"
docker compose -f infra/docker/docker-compose.yml ps

echo "[3/4] Health check"
curl -fsS -m 5 http://127.0.0.1/assistant/api/health >/dev/null

echo "[4/4] Kakao webhook smoke check"
curl -fsS -m 5 -X POST http://127.0.0.1/assistant/api/kakao/webhook \
  -H "Content-Type: application/json" \
  -d '{"userRequest":{"utterance":"헬스체크"}}' >/dev/null

echo "All validation checks passed."
