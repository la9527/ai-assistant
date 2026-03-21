#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="${AI_ASSISTANT_ROOT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
AI_STORAGE_ROOT="${AI_STORAGE_ROOT:-/Volumes/ExtData/ai-assistant}"
N8N_DB_TYPE="${N8N_DB_TYPE:-postgresdb}"
N8N_DATA_DIR="$AI_STORAGE_ROOT/docker/n8n"
BACKUP_ROOT="$AI_STORAGE_ROOT/backups/n8n-reset"
WORKFLOW_SOURCE_DIR="$ROOT_DIR/workflows/n8n"
N8N_CONTAINER_PATH="/tmp/assistant-workflows"
WAIT_TIMEOUT_SECONDS="${N8N_RESET_WAIT_TIMEOUT_SECONDS:-120}"
POLL_INTERVAL_SECONDS="${N8N_RESET_POLL_INTERVAL_SECONDS:-3}"

usage() {
  cat <<'EOF'
Usage: infra/scripts/reset-n8n-extdata-storage.sh [--import-only] [--skip-import]

This helper is only for legacy SQLite-based n8n recovery.

Options:
  --import-only  Skip backup/reset and only re-import repo workflows into the current n8n project.
  --skip-import  Reset storage but do not import workflows.
  -h, --help     Show this help message.

Behavior:
  1. Back up /Volumes/ExtData/ai-assistant/docker/n8n into /Volumes/ExtData/ai-assistant/backups/n8n-reset/<timestamp>
  2. Reset the ExtData-backed n8n storage directory
  3. Start n8n and wait for http://127.0.0.1:5678/healthz/readiness
  4. If an owner personal project exists, import workflows from workflows/n8n
EOF
}

import_only=false
skip_import=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --import-only)
      import_only=true
      ;;
    --skip-import)
      skip_import=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$import_only" == true && "$skip_import" == true ]]; then
  echo "--import-only and --skip-import cannot be used together" >&2
  exit 1
fi

if [[ "$N8N_DB_TYPE" != "sqlite" ]]; then
  echo "This helper only applies to legacy SQLite-based n8n storage. Current N8N_DB_TYPE=$N8N_DB_TYPE" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

if [[ ! -d "$WORKFLOW_SOURCE_DIR" ]]; then
  echo "Missing workflow source directory: $WORKFLOW_SOURCE_DIR" >&2
  exit 1
fi

mkdir -p "$N8N_DATA_DIR" "$BACKUP_ROOT"

compose_cmd=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

wait_for_n8n() {
  local waited_seconds=0

  until curl -fsS -m 5 http://127.0.0.1:5678/healthz/readiness >/dev/null; do
    if (( waited_seconds >= WAIT_TIMEOUT_SECONDS )); then
      echo "n8n readiness check timed out after ${WAIT_TIMEOUT_SECONDS}s" >&2
      return 1
    fi
    sleep "$POLL_INTERVAL_SECONDS"
    waited_seconds=$(( waited_seconds + POLL_INTERVAL_SECONDS ))
  done
}

backup_current_storage() {
  local timestamp backup_dir
  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_dir="$BACKUP_ROOT/$timestamp"
  mkdir -p "$backup_dir"

  if [[ -n "$(find "$N8N_DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "Backing up n8n storage to $backup_dir"
    rsync -a "$N8N_DATA_DIR/" "$backup_dir/"
  else
    echo "n8n storage directory is already empty; skipping data copy"
  fi
}

reset_storage() {
  echo "Stopping n8n service"
  "${compose_cmd[@]}" stop n8n

  echo "Resetting $N8N_DATA_DIR"
  find "$N8N_DATA_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +

  echo "Starting n8n service"
  "${compose_cmd[@]}" up -d n8n
  wait_for_n8n
}

get_personal_project_id() {
  local db_file query
  db_file="$N8N_DATA_DIR/database.sqlite"
  query="select id from project where type = 'personal' order by rowid asc limit 1;"

  if [[ ! -f "$db_file" ]]; then
    return 1
  fi

  sqlite3 "$db_file" "$query"
}

import_repo_workflows() {
  local project_id container_id

  project_id="$(get_personal_project_id || true)"
  if [[ -z "$project_id" ]]; then
    echo "No personal project found in n8n database yet." >&2
    echo "Complete the owner setup in the n8n UI, then rerun with --import-only." >&2
    return 2
  fi

  container_id="$("${compose_cmd[@]}" ps -q n8n)"
  if [[ -z "$container_id" ]]; then
    echo "Unable to resolve n8n container ID" >&2
    return 1
  fi

  echo "Copying workflows into n8n container"
  docker cp "$WORKFLOW_SOURCE_DIR/." "$container_id:$N8N_CONTAINER_PATH"

  echo "Importing workflows into project $project_id"
  "${compose_cmd[@]}" exec -T n8n n8n import:workflow --separate --input="$N8N_CONTAINER_PATH" --projectId="$project_id"
  "${compose_cmd[@]}" exec -u root -T n8n sh -lc "rm -rf '$N8N_CONTAINER_PATH'"

  echo "Reactivating imported assistant workflows"
  sqlite3 "$N8N_DATA_DIR/database.sqlite" \
    "update workflow_entity set active = 1, updatedAt = STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW') where name like 'assistant-%';"

  echo "Restarting n8n to rebuild webhook registrations"
  "${compose_cmd[@]}" restart n8n
  wait_for_n8n
}

if [[ "$import_only" == false ]]; then
  backup_current_storage
  reset_storage
fi

if [[ "$skip_import" == false ]]; then
  import_repo_workflows
fi

echo "n8n ExtData storage reset flow completed."