import httpx

from app.config import settings


def _normalize_reply_text(reply: str) -> str:
    normalized = reply.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


def generate_local_reply(message: str, channel: str) -> tuple[str, str]:
    endpoint = f"{settings.local_llm.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.local_llm.model,
        "messages": [
            {
                "role": "system",
                "content": "당신은 한국어로 간결하고 실용적으로 답하는 AI 개인 비서다.",
            },
            {
                "role": "user",
                "content": f"channel={channel}\nrequest={message}",
            },
        ],
        "temperature": 0.2,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
        body = response.json()
        reply = _normalize_reply_text(body["choices"][0]["message"]["content"])
        if not reply:
            raise ValueError("empty response")
        return reply, "local_llm"
    except Exception:
        fallback = (
            "현재 로컬 LLM 응답을 가져오지 못했습니다. "
            f"channel={channel}, provider={settings.local_llm.provider}, model={settings.local_llm.model}"
        )
        return fallback, "fallback"