"""비동기 작업 큐 클라이언트 — Redis LIST 기반 작업 발행.

API에서 Worker로 비동기 작업을 위임할 때 사용한다.
작업 결과는 Worker가 'assistant:results:{task_id}' 키에 저장한다.
"""

from __future__ import annotations

import json
import logging
import uuid

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")

TASK_QUEUE = "assistant:tasks"
RESULT_PREFIX = "assistant:results:"


def _get_redis():
    """Redis 연결을 반환한다. redis 패키지가 없으면 httpx 기반 대안을 사용."""
    try:
        import redis
        return redis.from_url(settings.redis_url, decode_responses=True)
    except ImportError:
        return None


def publish_task(task_type: str, payload: dict, task_id: str | None = None) -> str | None:
    """작업을 Redis 큐에 발행한다.

    Returns:
        task_id (성공 시) 또는 None (Redis 미연결 시)
    """
    r = _get_redis()
    if r is None:
        logger.warning("Redis not available, cannot publish task")
        return None

    task_id = task_id or str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "type": task_type,
        "payload": payload,
    }

    try:
        r.lpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False))
        logger.info("Published task %s type=%s", task_id, task_type)
        return task_id
    except Exception as exc:
        logger.warning("Failed to publish task: %s", exc)
        return None


def get_task_result(task_id: str) -> dict | None:
    """작업 결과를 Redis에서 조회한다."""
    r = _get_redis()
    if r is None:
        return None

    try:
        raw = r.get(f"{RESULT_PREFIX}{task_id}")
        if raw:
            return json.loads(raw)
        return None
    except Exception:
        return None
