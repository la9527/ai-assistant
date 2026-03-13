import httpx
import re
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.llm import generate_local_reply


CALENDAR_AUTOMATION_KEYWORDS = (
    "일정",
    "캘린더",
    "calendar",
)

GMAIL_AUTOMATION_KEYWORDS = (
    "메일",
    "이메일",
    "gmail",
    "email",
    "편지함",
    "수신",
    "참조",
    "bcc",
)

CALENDAR_CREATE_KEYWORDS = ("추가", "생성", "등록", "만들", "잡아")
CALENDAR_UPDATE_KEYWORDS = ("변경", "수정", "옮겨", "미뤄", "당겨", "재조정")
CALENDAR_DELETE_KEYWORDS = ("삭제", "취소", "지워", "제거", "없애")

GMAIL_DRAFT_KEYWORDS = ("초안", "draft")
GMAIL_SEND_KEYWORDS = ("발송", "send")
GMAIL_SUMMARY_KEYWORDS = ("요약", "최근", "편지함", "받은편지함", "inbox")
GMAIL_REPLY_KEYWORDS = ("답장", "회신", "reply")
GMAIL_THREAD_KEYWORDS = ("이어", "이어서", "계속", "thread", "스레드")

EMAIL_ADDRESS_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_PATTERN = re.compile(r"https?://[^\s,]+", re.IGNORECASE)
TIME_FRAGMENT_PATTERN = re.compile(
    r"(?:오전|오후)?\s*\d{1,2}(?:(?::\s*\d{2})|\s*시(?:\s*\d{1,2}\s*분?)?)\s*(?:반)?"
)
THREAD_ID_PATTERN = re.compile(r"(?:thread|스레드)\s*(?:id)?\s*[:=]?\s*([A-Za-z0-9_-]+)", re.IGNORECASE)
MESSAGE_ID_PATTERN = re.compile(r"(?:message|메시지|메일)\s*(?:id)?\s*[:=]?\s*([A-Za-z0-9_-]{10,})", re.IGNORECASE)

ACTION_LABELS = {
    "calendar_create": "생성",
    "calendar_update": "변경",
    "calendar_delete": "삭제",
    "gmail_draft": "초안 작성",
    "gmail_send": "발송",
    "gmail_reply": "회신",
    "gmail_thread_reply": "thread 이어쓰기",
}

GMAIL_COMPOSE_STOP_LABELS = (
    "참조",
    "cc",
    "bcc",
    "숨은참조",
    "숨은 참조",
    "받는사람",
    "받는 사람",
    "수신자",
    "수신",
    "발신자",
    "보낸 사람",
    "sender",
    "thread",
    "스레드",
    "message",
    "메시지",
    "첨부",
    "attachment",
    "메일 보내줘",
    "메일 보내 줘",
    "이메일 보내줘",
    "이메일 보내 줘",
    "메일 발송해줘",
    "메일 발송해 줘",
    "발송해줘",
    "발송해 줘",
    "메일 초안 작성해줘",
    "메일 초안 작성해 줘",
    "초안 작성해줘",
    "초안 작성해 줘",
    "초안 만들어줘",
    "초안 만들어 줘",
)


def classify_message_intent(message: str) -> str:
    lowered = message.lower()
    has_calendar_keyword = any(keyword in lowered for keyword in CALENDAR_AUTOMATION_KEYWORDS)
    has_gmail_keyword = any(keyword in lowered for keyword in GMAIL_AUTOMATION_KEYWORDS) or EMAIL_ADDRESS_PATTERN.search(message) is not None

    if any(keyword in message for keyword in CALENDAR_UPDATE_KEYWORDS) and any(
        keyword in lowered for keyword in CALENDAR_AUTOMATION_KEYWORDS
    ):
        return "calendar_update"
    if any(keyword in message for keyword in CALENDAR_CREATE_KEYWORDS) and any(
        keyword in lowered for keyword in CALENDAR_AUTOMATION_KEYWORDS
    ):
        return "calendar_create"
    if has_calendar_keyword and any(keyword in message for keyword in CALENDAR_DELETE_KEYWORDS):
        return "calendar_delete"
    if has_calendar_keyword:
        return "calendar_summary"

    if has_gmail_keyword and any(keyword in lowered for keyword in GMAIL_DRAFT_KEYWORDS):
        return "gmail_draft"
    if has_gmail_keyword and any(keyword in lowered for keyword in GMAIL_THREAD_KEYWORDS) and any(
        keyword in lowered for keyword in GMAIL_REPLY_KEYWORDS
    ):
        return "gmail_thread_reply"
    if has_gmail_keyword and any(keyword in lowered for keyword in GMAIL_REPLY_KEYWORDS):
        return "gmail_reply"
    if has_gmail_keyword and (
        any(keyword in lowered for keyword in GMAIL_SEND_KEYWORDS) or "보내" in message
    ) and not any(keyword in lowered for keyword in GMAIL_SUMMARY_KEYWORDS):
        return "gmail_send"
    if has_gmail_keyword:
        return "gmail_summary"
    return "chat"


def should_route_to_automation(message: str) -> bool:
    return classify_message_intent(message) != "chat"


def process_message(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
    intent_override: str | None = None,
    approval_granted: bool = False,
) -> dict[str, str | None]:
    intent = intent_override or classify_message_intent(message)

    if intent == "calendar_summary" and settings.n8n_webhook_path:
        reply = run_n8n_automation(message, channel, session_id, user_id, settings.n8n_webhook_path)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": None}
        fallback_reply, _ = generate_local_reply(message, channel)
        return {"reply": fallback_reply, "route": "n8n_fallback", "action_type": None}

    if intent in {"calendar_create", "calendar_update", "calendar_delete"}:
        parsed = parse_calendar_request(message, intent)
        if parsed is None:
            example = (
                "내일 오후 3시에 치과 일정 추가해줘"
                if intent == "calendar_create"
                else "내일 오후 4시 치과 일정 변경해줘"
                if intent == "calendar_update"
                else "내일 오후 3시 치과 일정 삭제해줘"
            )
            return {
                "reply": f"일정 요청을 이해하지 못했습니다. 예: {example}",
                "route": "validation_error",
                "action_type": intent,
            }
        if not approval_granted:
            action_label = ACTION_LABELS[intent]
            return {
                "reply": f"일정 {action_label} 요청입니다. 승인 후 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        webhook_path = {
            "calendar_create": settings.n8n_calendar_create_webhook_path,
            "calendar_update": settings.n8n_calendar_update_webhook_path,
            "calendar_delete": settings.n8n_calendar_delete_webhook_path,
        }[intent]
        reply = run_n8n_automation(message, channel, session_id, user_id, webhook_path, parsed)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": intent}
        fallback_reply = "승인된 일정 작업 실행에 실패했습니다. n8n workflow 또는 자격 증명을 확인하세요."
        return {"reply": fallback_reply, "route": "n8n_fallback", "action_type": intent}

    if intent in {"gmail_draft", "gmail_send"}:
        parsed = parse_gmail_compose_request(message, intent)
        if parsed is None:
            return {
                "reply": "메일 작성 요청을 이해하지 못했습니다. 예: test@example.com로 제목 주간 보고, 내용 오늘 작업 완료 메일 초안 작성해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        if not approval_granted:
            action_label = ACTION_LABELS[intent]
            return {
                "reply": f"메일 {action_label} 요청입니다. 승인 후 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        webhook_path = (
            settings.n8n_gmail_draft_webhook_path
            if intent == "gmail_draft"
            else settings.n8n_gmail_send_webhook_path
        )
        reply = run_n8n_automation(message, channel, session_id, user_id, webhook_path, parsed)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": intent}
        fallback_reply = "승인된 메일 작업 실행에 실패했습니다. n8n Gmail workflow 또는 credential 연결 상태를 확인하세요."
        return {"reply": fallback_reply, "route": "n8n_fallback", "action_type": intent}

    if intent in {"gmail_reply", "gmail_thread_reply"}:
        parsed = parse_gmail_reply_request(message, intent)
        if parsed is None:
            return {
                "reply": "메일 회신 요청을 이해하지 못했습니다. 예: 제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        if not approval_granted:
            action_label = ACTION_LABELS[intent]
            return {
                "reply": f"메일 {action_label} 요청입니다. 승인 후 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        reply = run_n8n_automation(
            message,
            channel,
            session_id,
            user_id,
            settings.n8n_gmail_reply_webhook_path,
            parsed,
        )
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": intent}
        return {
            "reply": "승인된 메일 회신 실행에 실패했습니다. n8n Gmail reply workflow 또는 credential 연결 상태를 확인하세요.",
            "route": "n8n_fallback",
            "action_type": intent,
        }

    if intent == "gmail_summary" and settings.n8n_gmail_webhook_path:
        reply = run_n8n_automation(message, channel, session_id, user_id, settings.n8n_gmail_webhook_path)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": None}
        return {
            "reply": "Gmail 자동화를 실행하지 못했습니다. n8n Gmail credential 연결 상태를 확인하세요.",
            "route": "n8n_fallback",
            "action_type": None,
        }

    reply, route = generate_local_reply(message, channel)
    return {"reply": reply, "route": route, "action_type": None}


def run_n8n_automation(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
    webhook_path: str | None = None,
    extra_payload: dict[str, str] | None = None,
) -> str | None:
    if not webhook_path:
        return None
    endpoint = f"{settings.n8n_base_url.rstrip('/')}/{webhook_path.lstrip('/')}"
    payload = {
        "message": message,
        "channel": channel,
        "session_id": session_id,
        "user_id": user_id,
    }
    if extra_payload:
        payload.update(extra_payload)
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


def parse_calendar_request(message: str, intent: str) -> dict[str, str] | None:
    base_date = _extract_base_date(message)
    time_info = _extract_time_range(message)
    title = _extract_calendar_title(message, intent)

    if not title or base_date is None:
        return None

    timezone = ZoneInfo("Asia/Seoul")
    search_time_min, search_time_max = _build_calendar_search_window(base_date, time_info, timezone)

    if intent == "calendar_delete":
        return {
            "search_title": title,
            "search_time_min": search_time_min,
            "search_time_max": search_time_max,
            "timezone": "Asia/Seoul",
        }

    if time_info is None:
        return None

    start_hour, start_minute, end_hour, end_minute = time_info
    start_dt = datetime(base_date.year, base_date.month, base_date.day, start_hour, start_minute, tzinfo=timezone)
    end_dt = datetime(base_date.year, base_date.month, base_date.day, end_hour, end_minute, tzinfo=timezone)

    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=1)

    result = {
        "title": title,
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
        "timezone": "Asia/Seoul",
    }
    if intent == "calendar_update":
        result["search_title"] = title
        result["new_title"] = title
        result["search_time_min"] = search_time_min
        result["search_time_max"] = search_time_max
    return result


def parse_gmail_compose_request(message: str, intent: str) -> dict[str, str] | None:
    send_to = _extract_recipient_list(message, ("받는사람", "받는 사람", "수신자", "수신", "to"))
    cc_list = _extract_recipient_list(message, ("참조", "참조자", "cc"))
    bcc_list = _extract_recipient_list(message, ("숨은참조", "숨은 참조", "bcc"))

    if send_to is None:
        to_match = re.search(
            rf"((?:{EMAIL_ADDRESS_PATTERN.pattern})(?:\s*,\s*(?:{EMAIL_ADDRESS_PATTERN.pattern}))*)\s*(?:에게|로)",
            message,
            re.IGNORECASE,
        )
        if to_match:
            send_to = ", ".join(_unique_preserve_order(EMAIL_ADDRESS_PATTERN.findall(to_match.group(1))))

    if send_to is None:
        found_emails = _unique_preserve_order(EMAIL_ADDRESS_PATTERN.findall(message))
        excluded = set()
        if cc_list:
            excluded.update(_split_emails(cc_list))
        if bcc_list:
            excluded.update(_split_emails(bcc_list))
        remaining = [email for email in found_emails if email not in excluded]
        if remaining:
            send_to = ", ".join(remaining)

    subject = _extract_labeled_segment(
        message,
        labels=("제목", "subject"),
        stop_labels=("내용", "본문", *GMAIL_COMPOSE_STOP_LABELS),
    )
    body = _extract_labeled_segment(
        message,
        labels=("내용", "본문", "message"),
        stop_labels=GMAIL_COMPOSE_STOP_LABELS,
    )

    if not send_to or not subject or not body:
        return None

    result = {
        "send_to": send_to,
        "subject": subject,
        "message": body,
        "email_type": "text",
    }
    if cc_list:
        result["cc_list"] = cc_list
    if bcc_list:
        result["bcc_list"] = bcc_list
    attachment_url = _extract_attachment_url(message)
    if attachment_url:
        result["attachment_url"] = attachment_url
    result["action"] = intent
    return result


def parse_gmail_reply_request(message: str, intent: str) -> dict[str, str] | None:
    subject = _extract_labeled_segment(
        message,
        labels=("제목", "subject"),
        stop_labels=("내용", "본문", "발신자", "보낸 사람", "sender", *GMAIL_COMPOSE_STOP_LABELS),
    )
    body = _extract_labeled_segment(
        message,
        labels=("내용", "본문", "message"),
        stop_labels=("발신자", "보낸 사람", "sender", *GMAIL_COMPOSE_STOP_LABELS),
    )
    sender = _extract_labeled_segment(
        message,
        labels=("발신자", "보낸 사람", "sender"),
        stop_labels=("제목", "subject", "내용", "본문", *GMAIL_COMPOSE_STOP_LABELS),
    )
    cc_list = _extract_recipient_list(message, ("참조", "참조자", "cc"))
    bcc_list = _extract_recipient_list(message, ("숨은참조", "숨은 참조", "bcc"))
    thread_id = _extract_pattern_value(THREAD_ID_PATTERN, message)
    message_id = _extract_pattern_value(MESSAGE_ID_PATTERN, message)

    if not body:
        return None

    result = {
        "reply_mode": "thread" if intent == "gmail_thread_reply" else "reply",
        "message": body,
        "email_type": "text",
    }
    if subject:
        result["subject"] = subject
    if sender:
        result["sender"] = sender
    if thread_id:
        result["thread_id"] = thread_id
    if message_id:
        result["message_id"] = message_id
    if cc_list:
        result["cc_list"] = cc_list
    if bcc_list:
        result["bcc_list"] = bcc_list
    attachment_url = _extract_attachment_url(message)
    if attachment_url:
        result["attachment_url"] = attachment_url

    search_query = _build_gmail_reply_search_query(subject, sender)
    if search_query:
        result["search_query"] = search_query

    if not result.get("thread_id") and not result.get("message_id") and not result.get("search_query"):
        return None

    return result


def _extract_base_date(message: str):
    timezone = ZoneInfo("Asia/Seoul")
    now = datetime.now(timezone).date()
    if "모레" in message:
        return now + timedelta(days=2)
    if "내일" in message:
        return now + timedelta(days=1)
    if "오늘" in message:
        return now
    explicit = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", message)
    if explicit:
        return datetime(int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3))).date()
    month_day = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", message)
    if month_day:
        return _resolve_month_day(now, int(month_day.group(1)), int(month_day.group(2)))
    numeric_month_day = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)", message)
    if numeric_month_day:
        return _resolve_month_day(now, int(numeric_month_day.group(1)), int(numeric_month_day.group(2)))
    return now


def _extract_time_range(message: str) -> tuple[int, int, int, int] | None:
    range_match = re.search(
        rf"({TIME_FRAGMENT_PATTERN.pattern})\s*(?:부터|에서|~|-)\s*({TIME_FRAGMENT_PATTERN.pattern})",
        message,
    )
    if range_match:
        start_hour, start_minute, meridiem = _parse_time_fragment(range_match.group(1))
        end_hour, end_minute, _ = _parse_time_fragment(range_match.group(2), fallback_meridiem=meridiem)
        return start_hour, start_minute, end_hour, end_minute

    match = TIME_FRAGMENT_PATTERN.search(message)
    if not match:
        return None

    hour, minute, _ = _parse_time_fragment(match.group(0))
    return hour, minute, hour + 1 if hour < 23 else hour, minute


def _extract_calendar_title(message: str, intent: str) -> str:
    working = message
    working = re.sub(r"(오늘|내일|모레|20\d{2}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}[./-]\d{1,2})", " ", working)
    working = re.sub(rf"{TIME_FRAGMENT_PATTERN.pattern}\s*(?:부터|에서|~|-)\s*{TIME_FRAGMENT_PATTERN.pattern}", " ", working)
    working = re.sub(TIME_FRAGMENT_PATTERN.pattern, " ", working)
    working = re.sub(r"(일정|캘린더|calendar)", " ", working, flags=re.IGNORECASE)
    if intent == "calendar_create":
        working = re.sub(r"(추가|생성|등록|만들어줘|만들어 줘|잡아줘|잡아 줘|해줘|해주세요)", " ", working)
    elif intent == "calendar_update":
        working = re.sub(r"(변경|수정|옮겨줘|옮겨 줘|미뤄줘|미뤄 줘|당겨줘|당겨 줘|해줘|해주세요)", " ", working)
    else:
        working = re.sub(r"(삭제|취소|지워줘|지워 줘|제거해줘|제거해 줘|없애줘|없애 줘|해줘|해주세요)", " ", working)
    working = re.sub(r"(으로|로|부터|까지)", " ", working)
    working = re.sub(r"\s+", " ", working).strip(" .,")
    return working


def _build_calendar_search_window(
    base_date,
    time_info: tuple[int, int, int, int] | None,
    timezone: ZoneInfo,
) -> tuple[str, str]:
    if time_info is None:
        day_start = datetime(base_date.year, base_date.month, base_date.day, 0, 0, tzinfo=timezone)
        day_end = datetime(base_date.year, base_date.month, base_date.day, 23, 59, 59, tzinfo=timezone)
        return day_start.isoformat(), day_end.isoformat()

    start_hour, start_minute, end_hour, end_minute = time_info
    search_start = datetime(base_date.year, base_date.month, base_date.day, start_hour, start_minute, tzinfo=timezone)
    search_end = datetime(base_date.year, base_date.month, base_date.day, end_hour, end_minute, tzinfo=timezone)
    if search_end <= search_start:
        search_end = search_start + timedelta(hours=1)
    return search_start.isoformat(), search_end.isoformat()


def _parse_time_fragment(fragment: str, fallback_meridiem: str | None = None) -> tuple[int, int, str | None]:
    match = re.search(
        r"(오전|오후)?\s*(\d{1,2})(?:(?::\s*(\d{2}))|\s*시(?:\s*(\d{1,2})\s*분?)?)\s*(반)?",
        fragment,
    )
    if not match:
        raise ValueError("invalid time fragment")

    meridiem = match.group(1) or fallback_meridiem
    hour = int(match.group(2))
    minute = int(match.group(3) or match.group(4) or (30 if match.group(5) else 0))
    if meridiem == "오후" and hour < 12:
        hour += 12
    if meridiem == "오전" and hour == 12:
        hour = 0
    return hour, minute, meridiem


def _resolve_month_day(now, month: int, day: int):
    candidate = datetime(now.year, month, day).date()
    if candidate < now - timedelta(days=1):
        candidate = datetime(now.year + 1, month, day).date()
    return candidate


def _extract_labeled_segment(
    message: str,
    labels: tuple[str, ...],
    stop_labels: tuple[str, ...],
) -> str | None:
    label_pattern = "|".join(sorted((re.escape(label) for label in labels), key=len, reverse=True))
    stop_pattern = "|".join(sorted((re.escape(label) for label in stop_labels), key=len, reverse=True))
    pattern = rf"(?:{label_pattern})\s*(?:은|는|이|가|을|를|:)?\s*(.+?)(?=\s*(?:{stop_pattern})\b|$)"
    match = re.search(pattern, message, re.IGNORECASE)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
    return value or None


def _extract_recipient_list(message: str, labels: tuple[str, ...]) -> str | None:
    segment = _extract_labeled_segment(
        message,
        labels=labels,
        stop_labels=("제목", "subject", "내용", "본문", *GMAIL_COMPOSE_STOP_LABELS),
    )
    if not segment:
        return None
    emails = _unique_preserve_order(EMAIL_ADDRESS_PATTERN.findall(segment))
    if not emails:
        return None
    return ", ".join(emails)


def _extract_pattern_value(pattern: re.Pattern[str], message: str) -> str | None:
    match = pattern.search(message)
    if not match:
        return None
    return match.group(1).strip()


def _build_gmail_reply_search_query(subject: str | None, sender: str | None) -> str | None:
    query_parts: list[str] = []
    if subject:
        query_parts.append(f'subject:"{subject}"')
    if sender:
        sender_email = EMAIL_ADDRESS_PATTERN.search(sender)
        if sender_email:
            query_parts.append(f'from:{sender_email.group(0)}')
        else:
            query_parts.append(f'from:"{sender}"')
    query_parts.append("newer_than:30d")
    if len(query_parts) == 1 and query_parts[0] == "newer_than:30d":
        return None
    return " ".join(query_parts)


def _extract_attachment_url(message: str) -> str | None:
    labeled_segment = _extract_labeled_segment(
        message,
        labels=("첨부", "attachment"),
        stop_labels=("제목", "subject", "내용", "본문", *GMAIL_COMPOSE_STOP_LABELS),
    )
    candidate_sources = [labeled_segment, message]
    for source in candidate_sources:
        if not source:
            continue
        match = URL_PATTERN.search(source)
        if match:
            return match.group(0).rstrip(").,!?")
    return None


def _split_emails(value: str) -> list[str]:
    return _unique_preserve_order(EMAIL_ADDRESS_PATTERN.findall(value))


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result