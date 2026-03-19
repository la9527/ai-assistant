"""Worker — Redis 기반 비동기 작업 큐 소비자.

Redis LIST 'assistant:tasks' 에서 JSON 작업을 BRPOP으로 가져와 처리한다.
결과는 'assistant:results:{task_id}' 키에 저장하고 TTL 600초로 만료시킨다.
"""

import json
import logging
import os
import time
import traceback

import httpx
import redis

logging.basicConfig(level=os.getenv("WORKER_LOG_LEVEL", "INFO"), format="%(asctime)s [worker] %(message)s")
logger = logging.getLogger("worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
TASK_QUEUE = "assistant:tasks"
RESULT_PREFIX = "assistant:results:"
RESULT_TTL = 600

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000/api")


def get_redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def process_task(task: dict) -> dict:
    """작업을 유형별로 처리한다."""
    task_type = task.get("type", "unknown")
    payload = task.get("payload", {})
    task_id = task.get("task_id", "")

    logger.info("Processing task %s type=%s", task_id, task_type)

    if task_type == "chat":
        return _handle_chat_task(payload)
    if task_type == "web_search":
        return _handle_web_search_task(payload)
    if task_type == "callback":
        return _handle_callback_task(payload)

    return {"status": "error", "message": f"알 수 없는 작업 유형: {task_type}"}


def _handle_chat_task(payload: dict) -> dict:
    """API의 /api/chat 엔드포인트를 호출하여 채팅 처리를 위임한다."""
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{API_BASE_URL}/chat", json=payload)
            resp.raise_for_status()
        return {"status": "completed", "result": resp.json()}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _handle_web_search_task(payload: dict) -> dict:
    """API의 /api/chat 엔드포인트를 통해 검색 작업을 처리한다."""
    chat_payload = {
        "message": payload.get("query", ""),
        "channel": payload.get("channel", "worker"),
        "session_id": payload.get("session_id", "worker-session"),
    }
    return _handle_chat_task(chat_payload)


def _handle_callback_task(payload: dict) -> dict:
    """결과를 콜백 URL로 전달한다."""
    callback_url = payload.get("callback_url")
    data = payload.get("data", {})
    if not callback_url:
        return {"status": "error", "message": "callback_url 누락"}
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(callback_url, json=data)
            resp.raise_for_status()
        return {"status": "completed", "callback_status": resp.status_code}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def main() -> None:
    logger.info("Starting worker — redis=%s queue=%s", REDIS_URL, TASK_QUEUE)

    while True:
        try:
            r = get_redis_client()
            logger.info("Connected to Redis, waiting for tasks...")
            break
        except Exception as exc:
            logger.warning("Redis connection failed, retrying in 5s: %s", exc)
            time.sleep(5)

    while True:
        try:
            result = r.brpop(TASK_QUEUE, timeout=10)
            if result is None:
                continue

            _, raw = result
            try:
                task = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in queue: %s", raw[:200])
                continue

            task_id = task.get("task_id", "unknown")
            task_result = process_task(task)

            result_key = f"{RESULT_PREFIX}{task_id}"
            r.setex(result_key, RESULT_TTL, json.dumps(task_result, ensure_ascii=False))
            logger.info("Task %s completed: %s", task_id, task_result.get("status"))

        except redis.ConnectionError:
            logger.warning("Redis connection lost, reconnecting in 5s...")
            time.sleep(5)
            try:
                r = get_redis_client()
            except Exception:
                pass
        except Exception:
            logger.error("Unexpected error: %s", traceback.format_exc())
            time.sleep(1)


if __name__ == "__main__":
    main()