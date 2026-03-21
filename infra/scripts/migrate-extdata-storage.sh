#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
AI_STORAGE_ROOT="${AI_STORAGE_ROOT:-/Volumes/ExtData/ai-assistant}"
MLX_CACHE_ROOT="${MLX_CACHE_ROOT:-$AI_STORAGE_ROOT/mlx}"

if [[ ! -d /Volumes/ExtData ]]; then
  echo "/Volumes/ExtData 를 찾지 못했습니다." >&2
  exit 1
fi

mkdir -p \
  "$AI_STORAGE_ROOT/docker/caddy/data" \
  "$AI_STORAGE_ROOT/docker/caddy/config" \
  "$AI_STORAGE_ROOT/docker/openwebui" \
  "$AI_STORAGE_ROOT/docker/n8n" \
  "$AI_STORAGE_ROOT/docker/postgres" \
  "$AI_STORAGE_ROOT/docker/redis" \
  "$AI_STORAGE_ROOT/docker/guacamole" \
  "$MLX_CACHE_ROOT/huggingface" \
  "$MLX_CACHE_ROOT/lmstudio"

compose_cmd=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

if docker info >/dev/null 2>&1; then
  "${compose_cmd[@]}" stop proxy webui api worker n8n redis postgres guacamole guacd guacamole-init cloudflared >/dev/null 2>&1 || true
fi

migrate_volume() {
  local volume_name="$1"
  local target_dir="$2"

  if ! docker volume inspect "$volume_name" >/dev/null 2>&1; then
    echo "skip volume: $volume_name (not found)"
    return 0
  fi

  mkdir -p "$target_dir"
  echo "migrating volume $volume_name -> $target_dir"
  docker run --rm \
    -v "$volume_name:/from:ro" \
    -v "$target_dir:/to" \
    alpine:latest sh -c 'cp -a /from/. /to/'
}

migrate_symlink_dir() {
  local source_dir="$1"
  local target_dir="$2"

  mkdir -p "$target_dir"

  if [[ -L "$source_dir" ]]; then
    echo "skip host dir: $source_dir (already symlink)"
    return 0
  fi

  if [[ -d "$source_dir" ]]; then
    echo "migrating host dir $source_dir -> $target_dir"
    rsync -a "$source_dir/" "$target_dir/"
    rm -rf "$source_dir"
    ln -s "$target_dir" "$source_dir"
  else
    ln -s "$target_dir" "$source_dir"
  fi
}

migrate_volume docker_caddy_data "$AI_STORAGE_ROOT/docker/caddy/data"
migrate_volume docker_caddy_config "$AI_STORAGE_ROOT/docker/caddy/config"
migrate_volume docker_openwebui_data "$AI_STORAGE_ROOT/docker/openwebui"
migrate_volume docker_n8n_data "$AI_STORAGE_ROOT/docker/n8n"
migrate_volume docker_postgres_data "$AI_STORAGE_ROOT/docker/postgres"
migrate_volume docker_redis_data "$AI_STORAGE_ROOT/docker/redis"
migrate_volume docker_guacamole_home "$AI_STORAGE_ROOT/docker/guacamole"

migrate_symlink_dir "$HOME/.cache/huggingface" "$MLX_CACHE_ROOT/huggingface"
migrate_symlink_dir "$HOME/.lmstudio" "$MLX_CACHE_ROOT/lmstudio"

echo "migration complete"
echo "AI_STORAGE_ROOT=$AI_STORAGE_ROOT"