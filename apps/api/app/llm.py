import json
import logging
import re

import httpx

from app.config import ExternalLLMSettings, settings
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


# ---------------------------------------------------------------------------
# Gmail summary formatting helpers
# ---------------------------------------------------------------------------

def _escape_mail_markdown(text: str) -> str:
    # Open WebUI treats \[ ... \] as KaTeX, so avoid escaping brackets.
    return re.sub(r"([\\`*_{}#!|])", r"\\\1", text)


def _clean_mail_text(value: object, fallback: str, *, collapse_whitespace: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"^[-*•]\s*", "", text)
    text = re.sub(r"^\*\*(.*?)\*\*$", r"\1", text)
    text = re.sub(r"^\d+[.)]\s*", "", text)
    text = re.sub(r"^\[(.+?)\]\s*", r"(\1) ", text)
    if collapse_whitespace:
        text = re.sub(r"\s+", " ", text).strip()
    return _escape_mail_markdown(text)


def _extract_gmail_detail_fields(raw_body: dict) -> dict[str, str]:
    detail = {
        "subject": _clean_mail_text(raw_body.get("subject"), "", collapse_whitespace=True),
        "sender": _clean_mail_text(raw_body.get("sender"), "", collapse_whitespace=True),
        "to": _clean_mail_text(raw_body.get("to"), "", collapse_whitespace=True),
        "date": _clean_mail_text(raw_body.get("date"), "", collapse_whitespace=True),
        "snippet": _clean_mail_text(raw_body.get("snippet"), "", collapse_whitespace=True),
        "body": _clean_mail_text(raw_body.get("body") or raw_body.get("bodyText") or raw_body.get("plainBody"), "", collapse_whitespace=True),
        "message_id": _clean_mail_text(raw_body.get("messageId") or raw_body.get("message_id"), "", collapse_whitespace=True),
        "thread_id": _clean_mail_text(raw_body.get("threadId") or raw_body.get("thread_id"), "", collapse_whitespace=True),
    }

    reply = raw_body.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        return detail

    lines = [line.rstrip() for line in reply.splitlines()]
    body_start = None
    field_patterns = {
        "subject": "제목:",
        "sender": "보낸 사람:",
        "to": "받는 사람:",
        "date": "날짜:",
        "message_id": "메시지 ID:",
        "thread_id": "스레드 ID:",
        "snippet": "미리보기:",
    }

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        normalized = re.sub(r"^[-*•]\s*", "", stripped)
        if normalized == "본문:":
            body_start = index + 1
            continue
        for key, prefix in field_patterns.items():
            if normalized.startswith(prefix) and not detail[key]:
                value = normalized[len(prefix):].strip()
                detail[key] = _clean_mail_text(value, "", collapse_whitespace=True)
                break

    if body_start is not None and not detail["body"]:
        body_lines = [line.strip() for line in lines[body_start:] if line.strip()]
        detail["body"] = _clean_mail_text("\n".join(body_lines), "", collapse_whitespace=True)

    return detail

def _format_gmail_items_markdown(items: list[dict]) -> str:
    """메일 아이템 목록을 WebUI 친화적인 Markdown으로 포맷한다."""
    if not items:
        return "최근 7일 이내 받은편지함 메일이 없습니다."

    lines = ["📬 **최근 메일 요약**", ""]
    for position, item in enumerate(items, start=1):
        idx = item.get("index") or position
        sender = _clean_mail_text(item.get("sender"), "발신자 미상")
        subject = _clean_mail_text(item.get("subject"), "제목 없음")
        snippet = _clean_mail_text(item.get("snippet"), "")
        date = _clean_mail_text(item.get("date"), "")

        lines.append(f"**{idx}) {subject}**")
        lines.append(f"보낸 사람: {sender}")
        if date:
            lines.append(f"날짜: {date}")
        if snippet:
            lines.append(f"미리보기: {snippet}")
        lines.append("")

    return "\n".join(lines)


def _format_gmail_items_compact(items: list[dict], reply: str) -> str:
    """Kakao 등 제한된 채널용 간결한 형식."""
    if not items:
        return reply or "최근 7일 이내 받은편지함 메일이 없습니다."
    lines = ["최근 메일 요약입니다."]
    for item in items:
        idx = item.get("index", "")
        sender = item.get("sender", "발신자 미상")
        subject = item.get("subject", "제목 없음")
        lines.append(f"{idx}. {sender} - {subject}")
    return "\n".join(lines)


def _format_gmail_detail_markdown(detail: dict[str, str]) -> str:
    lines = ["📩 **메일 상세 정보**", ""]

    subject = detail.get("subject") or "(제목 없음)"
    sender = detail.get("sender") or "발신자 미상"
    lines.append(f"**제목**: {subject}")
    lines.append(f"보낸 사람: {sender}")

    if detail.get("date"):
        lines.append(f"날짜: {detail['date']}")
    if detail.get("to"):
        lines.append(f"받는 사람: {detail['to']}")
    if detail.get("message_id"):
        lines.append(f"메시지 ID: {detail['message_id']}")
    if detail.get("thread_id"):
        lines.append(f"스레드 ID: {detail['thread_id']}")
    if detail.get("snippet"):
        lines.append(f"미리보기: {detail['snippet']}")
    if detail.get("body"):
        lines.extend(["", "**본문**", detail["body"]])

    return "\n".join(lines)


def _format_gmail_detail_compact(detail: dict[str, str], reply: str) -> str:
    if reply:
        return reply

    lines = ["메일 상세 정보입니다."]
    if detail.get("subject"):
        lines.append(f"제목: {detail['subject']}")
    if detail.get("sender"):
        lines.append(f"보낸 사람: {detail['sender']}")
    if detail.get("date"):
        lines.append(f"날짜: {detail['date']}")
    if detail.get("snippet"):
        lines.append(f"미리보기: {detail['snippet']}")
    return "\n".join(lines)


def format_gmail_action_reply(reply: str, channel: str) -> str:
    text = str(reply or "").strip()
    if not text or channel not in ("webui", "web", "api"):
        return text

    send_match = re.match(
        r"^(?P<recipient>.+?)로 메일을 발송했습니다\.\s*제목은 '(?P<subject>.+?)' 입니다\.(?P<attachment>\s*첨부파일 URL도 포함했습니다\.)?$",
        text,
    )
    if send_match:
        lines = [
            "메일을 발송했습니다.",
            f"수신: {send_match.group('recipient').strip()}",
            f"제목: {send_match.group('subject').strip()}",
        ]
        if send_match.group("attachment"):
            lines.append("첨부파일 URL도 포함했습니다.")
        return "\n".join(lines)

    draft_match = re.match(
        r"^(?P<recipient>.+?) 수신 메일 초안을 작성했습니다\.\s*제목은 '(?P<subject>.+?)' 입니다\.(?P<attachment>\s*첨부파일 URL도 포함했습니다\.)?$",
        text,
    )
    if draft_match:
        lines = [
            "메일 초안을 작성했습니다.",
            f"수신: {draft_match.group('recipient').strip()}",
            f"제목: {draft_match.group('subject').strip()}",
        ]
        if draft_match.group("attachment"):
            lines.append("첨부파일 URL도 포함했습니다.")
        return "\n".join(lines)

    reply_match = re.match(
        r"^(?P<mode>thread 이어쓰기|메일 회신)을 실행했습니다\.\s*대상은 '(?P<target>.+?)' 입니다\.(?P<attachment>\s*첨부파일 URL도 포함했습니다\.)?$",
        text,
    )
    if reply_match:
        lines = [
            f"{reply_match.group('mode')}을 실행했습니다.",
            f"대상: {reply_match.group('target').strip()}",
        ]
        if reply_match.group("attachment"):
            lines.append("첨부파일 URL도 포함했습니다.")
        return "\n".join(lines)

    not_found_match = re.match(
        r"^(?P<target>.+?)에 대한 회신 대상을 찾지 못했습니다\.\s*제목이나 thread id를 더 구체적으로 알려주세요\.$",
        text,
    )
    if not_found_match:
        return "\n".join([
            "회신 대상을 찾지 못했습니다.",
            f"대상: {not_found_match.group('target').strip()}",
            "제목이나 thread id를 더 구체적으로 알려주세요.",
        ])

    return text


def format_gmail_summary_with_llm(
    items: list[dict],
    channel: str,
) -> str | None:
    """외부 LLM을 사용해 메일 요약을 보기 좋게 포맷한다. 실패 시 None 반환."""
    ext = settings.external_llm
    if not ext.enabled or not ext.api_key:
        return None

    items_text = "\n".join(
        f"- 보낸 사람: {it.get('sender', '?')}, 제목: {it.get('subject', '?')}, "
        f"미리보기: {it.get('snippet', '')}, 날짜: {it.get('date', '')}"
        for it in items
    )

    messages = [
        {
            "role": "system",
            "content": (
                "당신은 메일 요약 포맷터이다. 아래 메일 목록을 읽기 좋은 Markdown으로 정리해 출력한다.\n"
                "규칙:\n"
                "- 각 메일을 번호 매기고, 제목을 굵게, 보낸 사람·날짜·미리보기를 하위 항목으로 정리한다.\n"
                "- 조치가 필요한 메일은 ⚠️ 아이콘으로 강조한다.\n"
                "- 마지막에 한 줄 요약(어떤 종류의 메일이 주로 왔는지)을 추가한다.\n"
                "- 다른 설명이나 인사말을 추가하지 마라. 포맷된 메일 목록만 출력하라."
            ),
        },
        {
            "role": "user",
            "content": f"다음 메일 목록을 보기 좋게 정리해줘:\n{items_text}",
        },
    ]

    try:
        reply = _call_external_llm(ext, messages, ext.model, temperature=0.2, max_tokens=1024)
        if reply and len(reply) > 20:
            return reply
        return None
    except Exception as exc:
        logger.warning("Gmail summary LLM formatting failed: %s", exc)
        return None


def format_gmail_summary(
    raw_body: dict,
    channel: str,
) -> str:
    """n8n 응답을 채널에 맞는 형식으로 포맷한다. 외부 LLM을 우선 시도한다."""
    items = raw_body.get("items", [])
    reply = raw_body.get("reply", "")

    # items가 없으면 reply 텍스트에서 파싱 시도
    if not items and reply:
        items = _parse_reply_to_items(reply)

    if not items:
        return reply or "최근 7일 이내 받은편지함 메일이 없습니다."

    # WebUI 채널: 항상 deterministic Markdown 포맷을 사용해 가독성을 유지한다.
    if channel in ("webui", "web", "api"):
        return _format_gmail_items_markdown(items)

    # Kakao 등 기타 채널: 간결한 텍스트
    return _format_gmail_items_compact(items, reply)


def format_gmail_detail(
    raw_body: dict,
    channel: str,
) -> str:
    reply = raw_body.get("reply", "")
    if raw_body.get("found") is False:
        return reply or "요청한 조건에 맞는 메일을 찾지 못했습니다."

    detail = _extract_gmail_detail_fields(raw_body)
    if channel in ("webui", "web", "api"):
        return _format_gmail_detail_markdown(detail)
    return _format_gmail_detail_compact(detail, reply)


def _parse_reply_to_items(reply: str) -> list[dict]:
    """구버전 n8n reply 텍스트 '1. sender - subject / 2. ...' 를 items로 파싱."""
    items: list[dict] = []
    # / 를 줄바꿈으로 정규화하고, 번호 앞에서도 줄바꿈
    normalized = re.sub(r"\s*/\s*(?=\d+\.)", "\n", reply)
    normalized = re.sub(r"(?<=[.!?。])\s+(?=\d+\.)", "\n", normalized)
    # 이메일 주소 내의 하이픈을 보호하기 위해 ' - ' (공백 포함) 구분자로 매칭
    for line in normalized.split("\n"):
        line = line.strip()
        m = re.search(r"(\d+)\.\s*(.+?)\s+- \s*(.+)", line)
        if m:
            items.append({
                "index": int(m.group(1)),
                "sender": m.group(2).strip(),
                "subject": m.group(3).strip(),
                "snippet": "",
                "date": "",
            })
    return items


def generate_external_reply(
    message: str,
    channel: str,
    memory_context: list[dict[str, str]] | None = None,
    *,
    provider_hint: str | None = None,
) -> tuple[str, str]:
    """외부 LLM(OpenAI/Claude/Gemini 등)을 통해 응답을 생성한다.

    provider_hint가 지정되면 해당 provider 전용 설정을 사용한다.
    """
    ext = settings.resolve_external_llm(provider_hint)
    if not ext.enabled or not ext.api_key:
        return "외부 LLM이 설정되지 않았습니다.", "fallback"

    messages = _build_local_reply_messages(message, channel, memory_context)
    try:
        reply = _call_external_llm(ext, messages, ext.model, temperature=0.3)
        if not reply:
            raise ValueError("empty response")
        return reply, "external_llm"
    except Exception as exc:
        logger.warning("External LLM reply failed provider=%s model=%s error=%s", ext.provider, ext.model, exc)
        return (
            "외부 LLM 응답을 가져오지 못했습니다. "
            f"provider={ext.provider}, model={ext.model}"
        ), "fallback"


# ---------------------------------------------------------------------------
# Multi-provider external LLM dispatcher
# ---------------------------------------------------------------------------

def _call_external_llm(
    ext: ExternalLLMSettings,
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    """provider에 따라 적절한 API 호출을 수행하고 텍스트 응답을 반환한다."""
    provider = ext.provider.lower()
    if provider == "anthropic":
        return _call_anthropic(ext, messages, model, temperature=temperature, max_tokens=max_tokens)
    elif provider == "gemini":
        return _call_gemini(ext, messages, model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
    else:
        return _call_openai_compatible(ext, messages, model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)


def _call_openai_compatible(
    ext: ExternalLLMSettings,
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    """OpenAI 호환 API (OpenAI, Together, Groq 등) 호출."""
    endpoint = f"{ext.base_url.rstrip('/')}/chat/completions"
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {ext.api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=ext.timeout_seconds) as client:
        response = client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
    body = response.json()
    return _normalize_reply_text(body["choices"][0]["message"]["content"])


def _call_anthropic(
    ext: ExternalLLMSettings,
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> str:
    """Anthropic Messages API 호출."""
    endpoint = f"{ext.base_url.rstrip('/')}/v1/messages"
    system_parts = []
    user_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            user_messages.append({"role": msg["role"], "content": msg["content"]})
    if not user_messages:
        user_messages.append({"role": "user", "content": ""})

    payload: dict[str, object] = {
        "model": model,
        "max_tokens": max_tokens or 4096,
        "messages": user_messages,
        "temperature": temperature,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    headers = {
        "x-api-key": ext.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=ext.timeout_seconds) as client:
        response = client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
    body = response.json()
    text_blocks = [b["text"] for b in body.get("content", []) if b.get("type") == "text"]
    return _normalize_reply_text("\n".join(text_blocks))


def _call_gemini(
    ext: ExternalLLMSettings,
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    """Google Gemini API 호출."""
    endpoint = (
        f"{ext.base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
        f"?key={ext.api_key}"
    )
    system_text = ""
    contents: list[dict] = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += msg["content"] + "\n"
        else:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    if not contents:
        contents.append({"role": "user", "parts": [{"text": ""}]})

    payload: dict[str, object] = {"contents": contents}
    if system_text.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}
    gen_config: dict[str, object] = {"temperature": temperature}
    if max_tokens:
        gen_config["maxOutputTokens"] = max_tokens
    if json_mode:
        gen_config["responseMimeType"] = "application/json"
    payload["generationConfig"] = gen_config

    headers = {"Content-Type": "application/json"}
    with httpx.Client(timeout=ext.timeout_seconds) as client:
        response = client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
    body = response.json()
    candidates = body.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(p.get("text", "") for p in parts)
    return _normalize_reply_text(text)


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

    intent = str(baseline.get("intent") or "")
    system_prompt = _build_structured_extraction_prompt(intent)
    user_prompt = {
        "channel": channel,
        "message": message,
        "recent_history": history[-8:] if history else [],
        "baseline_extraction": baseline,
    }
    user_content = json.dumps(user_prompt, ensure_ascii=False)

    # --- 외부 LLM 구조화 추출 시도 ---
    ext = settings.external_llm
    if ext.enabled and ext.structured_extraction_enabled and ext.api_key:
        ext_result = _try_external_structured_extraction(
            ext, system_prompt, user_content, baseline, message, channel, history,
        )
        if ext_result is not None:
            return ext_result
        logger.info("External structured extraction failed, falling back to local")

    # --- 로컬 LLM 구조화 추출 ---
    return _try_local_structured_extraction(
        system_prompt, user_content, baseline, message, channel, history,
    )


def _try_external_structured_extraction(
    ext: ExternalLLMSettings,
    system_prompt: str,
    user_content: str,
    baseline: dict[str, object],
    message: str,
    channel: str | None,
    history: list[dict[str, str]] | None,
) -> StructuredExtraction | None:
    """외부 LLM으로 구조화 추출을 시도한다."""
    model = ext.structured_extraction_model or ext.model
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    intent = str(baseline.get("intent") or "")

    for json_mode in (True, False):
        try:
            content = _call_external_llm(
                ext, messages, model,
                temperature=0.0,
                max_tokens=512,
                json_mode=json_mode,
            )
            extraction_raw = _extract_json_object(content)
            extraction_payload = _sanitize_structured_extraction_payload(
                json.loads(extraction_raw), baseline, message, channel,
            )
            extraction = StructuredExtraction.model_validate(extraction_payload)
            extraction.metadata = {
                **dict(extraction.metadata),
                "schema_mode": "external_llm_structured_extraction",
                "provider": ext.provider,
                "model": model,
                "history_size": len(history or []),
                "json_mode_used": json_mode,
                "llm_attempted": True,
                "llm_used": True,
            }
            return extraction
        except Exception as exc:
            logger.info(
                "External structured extraction retry intent=%s provider=%s model=%s json_mode=%s error=%s",
                intent, ext.provider, model, json_mode, exc,
            )
            continue
    return None


def _try_local_structured_extraction(
    system_prompt: str,
    user_content: str,
    baseline: dict[str, object],
    message: str,
    channel: str | None,
    history: list[dict[str, str]] | None,
) -> StructuredExtraction | None:
    """로컬 LLM으로 구조화 추출을 시도한다."""
    endpoint = f"{settings.local_llm.structured_extraction_base_url.rstrip('/')}/chat/completions"
    intent = str(baseline.get("intent") or "")
    base_payload = {
        "model": settings.local_llm.structured_extraction_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
                json.loads(content), baseline, message, channel,
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