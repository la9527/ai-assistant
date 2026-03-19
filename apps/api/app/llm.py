import json
import logging

import httpx

from app.config import settings
from app.schemas import StructuredExtraction


logger = logging.getLogger("uvicorn.error")


def _structured_prompt_examples(intent: str) -> str:
    examples = {
        "calendar_create": (
            '{"version":"1","rawMessage":"내일 오후 3시에 치과 일정 추가해줘","normalizedMessage":"내일 오후 3시에 치과 일정 추가해줘","channel":"web","domain":"calendar","action":"create","intent":"calendar_create","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":{"title":"치과","startAt":"2026-03-16T15:00:00+09:00","endAt":"2026-03-16T16:00:00+09:00","timezone":"Asia/Seoul"},"mail":null,"note":null,"metadata":{}}'
        ),
        "calendar_update": (
            '{"version":"1","rawMessage":"내일 오후 3시 치과 일정을 오후 4시로 변경해줘","normalizedMessage":"내일 오후 3시 치과 일정을 오후 4시로 변경해줘","channel":"web","domain":"calendar","action":"update","intent":"calendar_update","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":{"title":"치과","searchTitle":"치과","startAt":"2026-03-16T16:00:00+09:00","endAt":"2026-03-16T17:00:00+09:00","searchTimeMin":"2026-03-16T15:00:00+09:00","searchTimeMax":"2026-03-16T16:00:00+09:00","timezone":"Asia/Seoul"},"mail":null,"note":null,"metadata":{}}'
        ),
        "calendar_delete": (
            '{"version":"1","rawMessage":"오늘 06:00-07:00 피자 시키기 일정 삭제해줘","normalizedMessage":"오늘 06:00-07:00 피자 시키기 일정 삭제해줘","channel":"web","domain":"calendar","action":"delete","intent":"calendar_delete","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":{"searchTitle":"피자 시키기","searchTimeMin":"2026-03-15T06:00:00+09:00","searchTimeMax":"2026-03-15T07:00:00+09:00","timezone":"Asia/Seoul"},"mail":null,"note":null,"metadata":{}}'
        ),
        "gmail_reply": (
            '{"version":"1","rawMessage":"제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘","normalizedMessage":"제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘","channel":"web","domain":"mail","action":"reply","intent":"gmail_reply","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":null,"mail":{"replyMode":"reply","recipients":[],"cc":[],"bcc":[],"subject":"AI Assistant Gmail 발송 테스트","body":"확인했습니다","threadReference":null,"messageReference":null,"searchQuery":"subject:\"AI Assistant Gmail 발송 테스트\" newer_than:30d","attachmentUrls":[]},"note":null,"metadata":{}}'
        ),
        "gmail_thread_reply": (
            '{"version":"1","rawMessage":"제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 이어서 답장해줘","normalizedMessage":"제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 이어서 답장해줘","channel":"web","domain":"mail","action":"thread_reply","intent":"gmail_thread_reply","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":null,"mail":{"replyMode":"thread","recipients":[],"cc":[],"bcc":[],"subject":"AI Assistant Gmail 발송 테스트","body":"확인했습니다","threadReference":null,"messageReference":null,"searchQuery":"subject:\"AI Assistant Gmail 발송 테스트\" newer_than:30d","attachmentUrls":[]},"note":null,"metadata":{}}'
        ),
        "gmail_draft": (
            '{"version":"1","rawMessage":"test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘","normalizedMessage":"test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘","channel":"web","domain":"mail","action":"draft","intent":"gmail_draft","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":null,"mail":{"recipients":["test@example.com"],"cc":[],"bcc":[],"subject":"주간 보고","body":"오늘 작업 완료","threadReference":null,"messageReference":null,"searchQuery":null,"attachmentUrls":[]},"note":null,"metadata":{}}'
        ),
        "gmail_send": (
            '{"version":"1","rawMessage":"test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 보내줘","normalizedMessage":"test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 보내줘","channel":"web","domain":"mail","action":"send","intent":"gmail_send","confidence":0.9,"needsClarification":false,"approvalRequired":true,"missingFields":[],"references":[],"calendar":null,"mail":{"recipients":["test@example.com"],"cc":[],"bcc":[],"subject":"주간 보고","body":"오늘 작업 완료","threadReference":null,"messageReference":null,"searchQuery":null,"attachmentUrls":[]},"note":null,"metadata":{}}'
        ),
    }
    return examples.get(intent, "")


def _build_structured_extraction_prompt(intent: str) -> str:
    example = _structured_prompt_examples(intent)
    prompt = (
        "당신은 한국어 AI 비서의 구조화 추출기다. 반드시 JSON 객체 하나만 출력하고 그 외 설명, 마크다운, 코드펜스, 주석을 절대 추가하지 마라. "
        "baseline_extraction을 우선 보정하는 역할만 수행한다. baseline이 이미 맞으면 같은 의미를 유지한 JSON만 반환하라. "
        "최상위 필드는 version, rawMessage, normalizedMessage, channel, domain, action, intent, confidence, needsClarification, approvalRequired, missingFields, references, calendar, mail, note, metadata 만 사용한다. "
        "없는 값은 null 을 사용하라. 빈 문자열 \"\", 빈 배열 [] 를 calendar, mail, note 자리에 넣지 마라. "
        "calendar, mail, note 는 객체 또는 null 만 허용된다. references 는 배열만 허용된다. metadata 는 객체만 허용된다. "
        "normalizedMessage는 원문 의미를 유지한 정규화 문자열로 작성하고, 오타로 바꾸지 마라. "
        "calendar_create는 title, startAt, endAt 이 중요하다. calendar_update는 기존 일정 검색용 searchTitle/searchTimeMin/searchTimeMax 와 새 시간 startAt/endAt 을 함께 채운다. "
        "calendar_delete는 searchTitle, searchTimeMin, searchTimeMax 를 채운다. "
        "calendar_summary는 조회 범위인 searchTimeMin/searchTimeMax 가 중요하다. '오늘 일정'이면 오늘 0시~내일 0시, '이번 주'면 월요일~일요일, '내일'이면 내일 0시~모레 0시를 ISO 형식으로 채운다. searchTitle이 언급되면 함께 채운다. "
        "gmail_summary는 searchQuery 가 중요하다. '오늘 메일'이면 newer_than:1d, '이번 주'면 newer_than:7d, '최근 메일'이면 newer_than:3d 를 넣는다. 발신자, 제목이 언급되면 from:, subject: 를 추가한다. "
        "gmail_reply는 body와 searchQuery 또는 threadReference/messageReference 중 하나가 중요하다. "
        "답장 본문 body에는 '메일에 답장해줘' 같은 작업 지시문을 넣지 말고 실제 답장 내용만 남겨라. "
        "정보가 부족하면 needsClarification=true 와 missingFields를 채워라. 위험 작업은 approvalRequired=true 를 유지하라."
    )
    if example:
        prompt += f" 예시: {example}"
    return prompt


def _nullify_blank(value: object) -> object:
    if value in ("", [], {}):
        return None
    return value


def _sanitize_mail_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return _nullify_blank(payload)
    sanitized = dict(payload)
    for key in ("replyMode", "sender", "subject", "body", "threadReference", "messageReference", "searchQuery"):
        if key in sanitized and sanitized[key] == "":
            sanitized[key] = None
    for key in ("recipients", "cc", "bcc", "attachmentUrls"):
        if key not in sanitized or sanitized[key] in (None, ""):
            sanitized[key] = []
    if isinstance(sanitized.get("body"), str):
        sanitized["body"] = sanitized["body"].replace("메일에 답장해줘", "").replace("답장해줘", "").strip()
    return sanitized


def _sanitize_calendar_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return _nullify_blank(payload)
    sanitized = dict(payload)
    for key in ("title", "searchTitle", "date", "startAt", "endAt", "searchTimeMin", "searchTimeMax", "timezone"):
        if key in sanitized and sanitized[key] == "":
            sanitized[key] = None
    return sanitized


def _sanitize_note_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return _nullify_blank(payload)
    sanitized = dict(payload)
    for key in ("title", "body", "folder"):
        if key in sanitized and sanitized[key] == "":
            sanitized[key] = None
    return sanitized


def _sanitize_structured_extraction_payload(
    payload: dict[str, object],
    baseline: dict[str, object],
    message: str,
    channel: str | None,
) -> dict[str, object]:
    sanitized = dict(payload)
    sanitized["rawMessage"] = sanitized.get("rawMessage") or message
    sanitized["normalizedMessage"] = sanitized.get("normalizedMessage") or sanitized["rawMessage"]
    sanitized["channel"] = sanitized.get("channel") or channel
    sanitized["domain"] = sanitized.get("domain") or baseline.get("domain")
    sanitized["action"] = sanitized.get("action") or baseline.get("action")
    sanitized["intent"] = sanitized.get("intent") or baseline.get("intent")
    sanitized["references"] = sanitized.get("references") if isinstance(sanitized.get("references"), list) else []
    sanitized["metadata"] = sanitized.get("metadata") if isinstance(sanitized.get("metadata"), dict) else {}
    sanitized["calendar"] = _sanitize_calendar_payload(sanitized.get("calendar"))
    sanitized["mail"] = _sanitize_mail_payload(sanitized.get("mail"))
    sanitized["note"] = _sanitize_note_payload(sanitized.get("note"))
    return sanitized


def _normalize_reply_text(reply: str) -> str:
    normalized = reply.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


def _build_memory_context_message(memory_context: list[dict[str, str]] | None) -> str | None:
    if not memory_context:
        return None

    lines: list[str] = []
    for item in memory_context[:6]:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        category = (item.get("category") or "general").strip() or "general"
        source = (item.get("source") or "manual").strip() or "manual"
        label = category if source == "manual" else f"{category}/{source}"
        trimmed = content if len(content) <= 180 else f"{content[:177].rstrip()}..."
        lines.append(f"- [{label}] {trimmed}")

    if not lines:
        return None

    return (
        "다음은 같은 사용자의 장기 메모리다. 검증된 사실처럼 단정하지 말고 참고 문맥으로만 활용하라. "
        "현재 요청과 충돌하면 최신 사용자 지시를 우선한다.\n"
        + "\n".join(lines)
    )


def _build_local_reply_messages(
    message: str,
    channel: str,
    memory_context: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": "당신은 한국어로 간결하고 실용적으로 답하는 AI 개인 비서다.",
        }
    ]
    memory_message = _build_memory_context_message(memory_context)
    if memory_message:
        messages.append({"role": "system", "content": memory_message})
    messages.append(
        {
            "role": "user",
            "content": f"channel={channel}\nrequest={message}",
        }
    )
    return messages


def _build_local_reply_payload(
    message: str,
    channel: str,
    memory_context: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "model": settings.local_llm.model,
        "messages": _build_local_reply_messages(message, channel, memory_context),
        "temperature": 0.2,
    }


def warm_local_llm() -> bool:
    if not settings.local_llm.prewarm_enabled:
        return False

    endpoint = f"{settings.local_llm.base_url.rstrip('/')}/chat/completions"
    payload = _build_local_reply_payload("짧게 준비 완료라고만 답해줘", "startup")
    payload["max_tokens"] = 24

    try:
        with httpx.Client(timeout=settings.local_llm.timeout_seconds) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
        body = response.json()
        reply = _normalize_reply_text(body["choices"][0]["message"]["content"])
        logger.info("Local LLM prewarm succeeded model=%s reply=%r", settings.local_llm.model, reply)
        return True
    except Exception as exc:
        logger.warning("Local LLM prewarm failed model=%s error=%s", settings.local_llm.model, exc)
        return False


def generate_local_reply(
    message: str,
    channel: str,
    memory_context: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    endpoint = f"{settings.local_llm.base_url.rstrip('/')}/chat/completions"
    payload = _build_local_reply_payload(message, channel, memory_context)

    try:
        with httpx.Client(timeout=settings.local_llm.timeout_seconds) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
        body = response.json()
        reply = _normalize_reply_text(body["choices"][0]["message"]["content"])
        if not reply:
            raise ValueError("empty response")
        return reply, "local_llm"
    except Exception:
        ext = settings.external_llm
        if ext.enabled and ext.fallback_only:
            ext_reply, ext_route = generate_external_reply(message, channel, memory_context)
            if ext_route == "external_llm":
                return ext_reply, ext_route
        fallback = (
            "현재 로컬 LLM 응답을 가져오지 못했습니다. "
            f"channel={channel}, provider={settings.local_llm.provider}, model={settings.local_llm.model}"
        )
        return fallback, "fallback"


def generate_external_reply(
    message: str,
    channel: str,
    memory_context: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    """외부 LLM(OpenAI/Claude 등)을 통해 응답을 생성한다."""
    ext = settings.external_llm
    if not ext.enabled or not ext.api_key:
        return "외부 LLM이 설정되지 않았습니다.", "fallback"

    endpoint = f"{ext.base_url.rstrip('/')}/chat/completions"
    messages = _build_local_reply_messages(message, channel, memory_context)
    payload = {
        "model": ext.model,
        "messages": messages,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {ext.api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=ext.timeout_seconds) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
        body = response.json()
        reply = _normalize_reply_text(body["choices"][0]["message"]["content"])
        if not reply:
            raise ValueError("empty response")
        return reply, "external_llm"
    except Exception:
        return (
            "외부 LLM 응답을 가져오지 못했습니다. "
            f"provider={ext.provider}, model={ext.model}"
        ), "fallback"


def _strip_json_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[1:-1]).strip()
    return normalized


def _extract_json_object(text: str) -> str:
    normalized = _strip_json_fence(text)
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return normalized
    return normalized[start : end + 1]


def generate_structured_extraction(
    message: str,
    channel: str | None,
    history: list[dict[str, str]] | None,
    baseline: dict[str, object],
) -> StructuredExtraction | None:
    if not settings.local_llm.structured_extraction_enabled:
        return None

    endpoint = f"{settings.local_llm.structured_extraction_base_url.rstrip('/')}/chat/completions"
    intent = str(baseline.get("intent") or "")
    system_prompt = _build_structured_extraction_prompt(intent)
    user_prompt = {
        "channel": channel,
        "message": message,
        "recent_history": history[-8:] if history else [],
        "baseline_extraction": baseline,
    }
    base_payload = {
        "model": settings.local_llm.structured_extraction_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }
    payload_candidates = [
        {**base_payload, "response_format": {"type": "json_object"}},
        base_payload,
    ]

    for payload in payload_candidates:
        try:
            with httpx.Client(timeout=settings.local_llm.structured_extraction_timeout_seconds) as client:
                response = client.post(endpoint, json=payload)
                response.raise_for_status()
            body = response.json()
            content = _extract_json_object(body["choices"][0]["message"]["content"])
            extraction_payload = _sanitize_structured_extraction_payload(
                json.loads(content),
                baseline,
                message,
                channel,
            )
            extraction = StructuredExtraction.model_validate(extraction_payload)
            extraction.metadata = {
                **dict(extraction.metadata),
                "schema_mode": "llm_structured_extraction",
                "model": settings.local_llm.structured_extraction_model,
                "history_size": len(history or []),
                "response_format_used": "response_format" in payload,
                "llm_attempted": True,
                "llm_used": True,
            }
            return extraction
        except Exception as exc:
            logger.info(
                "Structured extraction parse retry intent=%s model=%s response_format=%s error=%s",
                intent,
                settings.local_llm.structured_extraction_model,
                "response_format" in payload,
                exc,
            )
            continue
    return None