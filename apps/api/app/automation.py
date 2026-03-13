import httpx

from app.config import settings
from app.llm import generate_local_reply


AUTOMATION_KEYWORDS = (
    "일정",
    "캘린더",
    "calendar",
    "메일",
    "email",
    "gmail",
    "notion",
    "노션",
)


def should_route_to_automation(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in AUTOMATION_KEYWORDS)


def process_message(message: str, channel: str, session_id: str, user_id: str | None = None) -> tuple[str, str]:
    if should_route_to_automation(message) and settings.n8n_webhook_path:
        reply = run_n8n_automation(message, channel, session_id, user_id)
        if reply is not None:
            return reply, "n8n"
        fallback_reply, _ = generate_local_reply(message, channel)
        return fallback_reply, "n8n_fallback"
    return generate_local_reply(message, channel)


def run_n8n_automation(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
) -> str | None:
    endpoint = f"{settings.n8n_base_url.rstrip('/')}/{settings.n8n_webhook_path.lstrip('/')}"
    payload = {
        "message": message,
        "channel": channel,
        "session_id": session_id,
        "user_id": user_id,
    }
    headers: dict[str, str] = {}
    if settings.n8n_webhook_token:
        headers["Authorization"] = f"Bearer {settings.n8n_webhook_token}"

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            if isinstance(body.get("reply"), str) and body["reply"].strip():
                return body["reply"].strip()
            if isinstance(body.get("message"), str) and body["message"].strip():
                return body["message"].strip()
        return "자동화 작업을 접수했습니다. 결과를 후속 메시지로 전달하겠습니다."
    except Exception:
        return None