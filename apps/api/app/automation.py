import httpx
import re
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.llm import generate_structured_extraction
from app.llm import generate_local_reply
from app.schemas import CalendarExtractionPayload
from app.schemas import MailExtractionPayload
from app.schemas import NoteExtractionPayload
from app.schemas import StructuredExtraction


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
CALENDAR_REFERENCE_PATTERN = re.compile(
    r"(오늘|내일|모레|20\d{2}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일|(?<!\d)\d{1,2}[./-]\d{1,2}(?!\d))"
)

GMAIL_DRAFT_KEYWORDS = ("초안", "draft")
GMAIL_SEND_KEYWORDS = ("발송", "send")
GMAIL_SUMMARY_KEYWORDS = ("요약", "최근", "편지함", "받은편지함", "inbox")
GMAIL_REPLY_KEYWORDS = ("답장", "회신", "reply")
GMAIL_THREAD_KEYWORDS = ("이어", "이어서", "계속", "thread", "스레드")
MACOS_NOTE_KEYWORDS = ("메모", "노트", "notes")
MACOS_NOTE_CREATE_KEYWORDS = ("추가", "작성", "저장", "기록", "남겨", "만들")

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
    "macos_note_create": "macOS 메모 생성",
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

MACOS_NOTE_ACTION_STOP_LABELS = (
    "추가",
    "작성",
    "저장",
    "기록",
    "남겨",
    "만들",
    "해줘",
    "해주세요",
)

CALENDAR_TITLE_STOP_TOKENS = {
    "에",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "도",
    "만",
    "내용",
    "내용을",
    "내용를",
    "내용만",
    "일정",
    "일정을",
    "일정만",
}
CALENDAR_TITLE_NOISE_PATTERN = re.compile(r"[0-9:.-]+")
GMAIL_REPLY_BODY_PREFIX_PATTERN = re.compile(r"^(?:답장\s*내용|회신\s*내용|내용|본문)\s*[:：-]?\s*", re.IGNORECASE)
GMAIL_REPLY_BODY_SUFFIX_PATTERNS = (
    re.compile(r"\s*메일에\s*(?:이어서\s*)?답장해\s*줘\s*$"),
    re.compile(r"\s*메일에\s*회신해\s*줘\s*$"),
    re.compile(r"\s*(?:이어서\s*)?답장해\s*줘\s*$"),
    re.compile(r"\s*회신해\s*줘\s*$"),
)


def extract_structured_request(
    message: str,
    channel: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> StructuredExtraction:
    baseline = _extract_rule_based_request(message, channel)
    if baseline.intent in settings.local_llm.structured_extraction_targets:
        llm_extraction = generate_structured_extraction(
            message,
            channel,
            history,
            baseline.model_dump(by_alias=True, exclude_none=True),
        )
        if llm_extraction is not None:
            return _merge_structured_extraction(baseline, llm_extraction)
        baseline.metadata = {
            **dict(baseline.metadata),
            "llm_attempted": True,
            "llm_used": False,
        }
    return baseline


def _extract_rule_based_request(message: str, channel: str | None = None) -> StructuredExtraction:
    intent = classify_message_intent(message)
    normalized_message = re.sub(r"\s+", " ", message).strip()
    domain, action = _resolve_domain_action(intent)
    approval_required = intent in ACTION_LABELS
    confidence = 0.85 if intent != "chat" else 0.45
    missing_fields: list[str] = []
    needs_clarification = False
    calendar_payload = None
    mail_payload = None
    note_payload = None

    if intent in {"calendar_create", "calendar_update", "calendar_delete"}:
        parsed = parse_calendar_request(message, intent)
        if parsed is None:
            needs_clarification = True
            confidence = 0.55
            missing_fields = ["title", "date_or_time"] if intent == "calendar_delete" else ["title", "date", "time"]
        else:
            calendar_payload = CalendarExtractionPayload.model_validate(parsed)
    elif intent in {"gmail_draft", "gmail_send", "gmail_reply", "gmail_thread_reply"}:
        parsed = (
            parse_gmail_compose_request(message, intent)
            if intent in {"gmail_draft", "gmail_send"}
            else parse_gmail_reply_request(message, intent)
        )
        if parsed is None:
            needs_clarification = True
            confidence = 0.55
            missing_fields = ["message", "target"] if intent in {"gmail_reply", "gmail_thread_reply"} else ["recipients", "subject", "body"]
        else:
            mail_payload = MailExtractionPayload(
                recipients=_split_emails(parsed.get("send_to", "")) if parsed.get("send_to") else [],
                cc=_split_emails(parsed.get("cc_list", "")) if parsed.get("cc_list") else [],
                bcc=_split_emails(parsed.get("bcc_list", "")) if parsed.get("bcc_list") else [],
                subject=parsed.get("subject"),
                body=parsed.get("message"),
                threadReference=parsed.get("thread_id"),
                messageReference=parsed.get("message_id"),
                searchQuery=parsed.get("search_query"),
                attachmentUrls=[parsed["attachment_url"]] if parsed.get("attachment_url") else [],
            )
    elif intent == "macos_note_create":
        parsed = parse_macos_note_request(message)
        if parsed is None:
            needs_clarification = True
            confidence = 0.55
            missing_fields = ["title", "body"]
        else:
            note_payload = NoteExtractionPayload.model_validate(parsed)

    return StructuredExtraction(
        rawMessage=message,
        normalizedMessage=normalized_message,
        channel=channel,
        domain=domain,
        action=action,
        intent=intent,
        confidence=confidence,
        needsClarification=needs_clarification,
        approvalRequired=approval_required,
        missingFields=missing_fields,
        calendar=calendar_payload,
        mail=mail_payload,
        note=note_payload,
        metadata={
            "schema_mode": "rule_based_baseline",
        },
    )


def _resolve_domain_action(intent: str) -> tuple[str, str]:
    if intent.startswith("calendar"):
        return "calendar", intent.removeprefix("calendar_")
    if intent.startswith("gmail"):
        return "mail", intent.removeprefix("gmail_")
    if intent.startswith("macos_note"):
        return "note", "create"
    if intent == "chat":
        return "chat", "respond"
    return "unknown", intent


def _prefer_text(primary: str | None, fallback: str | None) -> str | None:
    if primary is None:
        return fallback
    if isinstance(primary, str) and primary == "":
        return fallback
    return primary


def _prefer_llm_text(llm_value: str | None, baseline_value: str | None) -> str | None:
    if llm_value is None:
        return baseline_value
    if isinstance(llm_value, str) and llm_value == "":
        return baseline_value
    return llm_value


def _merge_calendar_payload(
    baseline: CalendarExtractionPayload | None,
    llm_payload: CalendarExtractionPayload | None,
) -> CalendarExtractionPayload | None:
    if baseline is None:
        return llm_payload
    if llm_payload is None:
        return baseline
    return CalendarExtractionPayload(
        title=_prefer_text(baseline.title, llm_payload.title),
        searchTitle=_prefer_text(baseline.search_title, llm_payload.search_title),
        date=_prefer_text(baseline.date, llm_payload.date),
        startAt=_prefer_text(baseline.start_at, llm_payload.start_at),
        endAt=_prefer_text(baseline.end_at, llm_payload.end_at),
        searchTimeMin=_prefer_text(baseline.search_time_min, llm_payload.search_time_min),
        searchTimeMax=_prefer_text(baseline.search_time_max, llm_payload.search_time_max),
        timezone=_prefer_text(baseline.timezone, llm_payload.timezone),
    )


def _merge_mail_payload(
    baseline: MailExtractionPayload | None,
    llm_payload: MailExtractionPayload | None,
) -> MailExtractionPayload | None:
    if baseline is None:
        return llm_payload
    if llm_payload is None:
        return baseline
    reply_mode = _prefer_llm_text(llm_payload.reply_mode, baseline.reply_mode)
    merged_body = _prefer_llm_text(llm_payload.body, baseline.body)
    if reply_mode in {"reply", "thread"}:
        merged_body = _normalize_gmail_reply_body(merged_body)
    return MailExtractionPayload(
        replyMode=reply_mode,
        recipients=baseline.recipients or llm_payload.recipients,
        cc=baseline.cc or llm_payload.cc,
        bcc=baseline.bcc or llm_payload.bcc,
        sender=_prefer_llm_text(llm_payload.sender, baseline.sender),
        subject=_prefer_llm_text(llm_payload.subject, baseline.subject),
        body=merged_body,
        threadReference=_prefer_llm_text(llm_payload.thread_reference, baseline.thread_reference),
        messageReference=_prefer_llm_text(llm_payload.message_reference, baseline.message_reference),
        searchQuery=_prefer_llm_text(llm_payload.search_query, baseline.search_query),
        attachmentUrls=baseline.attachment_urls or llm_payload.attachment_urls,
    )


def _merge_note_payload(
    baseline: NoteExtractionPayload | None,
    llm_payload: NoteExtractionPayload | None,
) -> NoteExtractionPayload | None:
    if baseline is None:
        return llm_payload
    if llm_payload is None:
        return baseline
    return NoteExtractionPayload(
        title=_prefer_text(baseline.title, llm_payload.title),
        body=_prefer_text(baseline.body, llm_payload.body),
        folder=_prefer_text(baseline.folder, llm_payload.folder),
    )


def _merge_structured_extraction(
    baseline: StructuredExtraction,
    llm_extraction: StructuredExtraction,
) -> StructuredExtraction:
    merged = StructuredExtraction(
        version=baseline.version,
        rawMessage=baseline.raw_message,
        normalizedMessage=baseline.normalized_message,
        channel=baseline.channel,
        domain=baseline.domain,
        action=baseline.action,
        intent=baseline.intent,
        confidence=max(baseline.confidence, llm_extraction.confidence),
        needsClarification=llm_extraction.needs_clarification,
        approvalRequired=baseline.approval_required,
        missingFields=llm_extraction.missing_fields or baseline.missing_fields,
        references=llm_extraction.references or baseline.references,
        calendar=_merge_calendar_payload(baseline.calendar, llm_extraction.calendar),
        mail=_merge_mail_payload(baseline.mail, llm_extraction.mail),
        note=_merge_note_payload(baseline.note, llm_extraction.note),
        metadata={
            **dict(llm_extraction.metadata),
            "merged_with_baseline": True,
        },
    )
    return merged


def _calendar_payload_to_request(payload: CalendarExtractionPayload | None, intent: str) -> dict[str, str] | None:
    if payload is None:
        return None
    if intent == "calendar_create":
        if not payload.title or not payload.start_at or not payload.end_at:
            return None
        return {
            "title": payload.title,
            "start_at": payload.start_at,
            "end_at": payload.end_at,
            "timezone": payload.timezone or "Asia/Seoul",
        }
    if intent == "calendar_update":
        if (
            not payload.title
            or not payload.start_at
            or not payload.end_at
            or not payload.search_title
            or not payload.search_time_min
            or not payload.search_time_max
        ):
            return None
        return {
            "title": payload.title,
            "start_at": payload.start_at,
            "end_at": payload.end_at,
            "search_title": payload.search_title,
            "new_title": payload.title,
            "search_time_min": payload.search_time_min,
            "search_time_max": payload.search_time_max,
            "timezone": payload.timezone or "Asia/Seoul",
        }
    if intent == "calendar_delete":
        if not payload.search_title or not payload.search_time_min or not payload.search_time_max:
            return None
        return {
            "search_title": payload.search_title,
            "search_time_min": payload.search_time_min,
            "search_time_max": payload.search_time_max,
            "timezone": payload.timezone or "Asia/Seoul",
        }
    return None


def _mail_payload_to_reply_request(payload: MailExtractionPayload | None, intent: str) -> dict[str, str] | None:
    if payload is None or not payload.body:
        return None
    cleaned_body = _normalize_gmail_reply_body(payload.body)
    if not cleaned_body:
        return None
    result = {
        "reply_mode": payload.reply_mode or ("thread" if intent == "gmail_thread_reply" else "reply"),
        "message": cleaned_body,
        "email_type": "text",
    }
    if payload.subject:
        result["subject"] = payload.subject
    if payload.sender:
        result["sender"] = payload.sender
    if payload.thread_reference:
        result["thread_id"] = payload.thread_reference
    if payload.message_reference:
        result["message_id"] = payload.message_reference
    if payload.search_query:
        result["search_query"] = payload.search_query
    if payload.cc:
        result["cc_list"] = ", ".join(payload.cc)
    if payload.bcc:
        result["bcc_list"] = ", ".join(payload.bcc)
    if payload.attachment_urls:
        result["attachment_url"] = payload.attachment_urls[0]
    if not result.get("thread_id") and not result.get("message_id") and not result.get("search_query"):
        return None
    return result


def _normalize_gmail_reply_body(body: str | None) -> str | None:
    if not body:
        return None
    normalized = body.strip()
    normalized = GMAIL_REPLY_BODY_PREFIX_PATTERN.sub("", normalized)
    for pattern in GMAIL_REPLY_BODY_SUFFIX_PATTERNS:
        normalized = pattern.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .,!?:;\n\t")
    return normalized or None


def _mail_payload_to_compose_request(payload: MailExtractionPayload | None, intent: str) -> dict[str, str] | None:
    if payload is None or not payload.recipients or not payload.subject or not payload.body:
        return None
    result = {
        "send_to": ", ".join(payload.recipients),
        "subject": payload.subject,
        "message": payload.body,
        "email_type": "text",
        "action": intent,
    }
    if payload.cc:
        result["cc_list"] = ", ".join(payload.cc)
    if payload.bcc:
        result["bcc_list"] = ", ".join(payload.bcc)
    if payload.attachment_urls:
        result["attachment_url"] = payload.attachment_urls[0]
    return result


def classify_message_intent(message: str) -> str:
    lowered = message.lower()
    has_calendar_keyword = any(keyword in lowered for keyword in CALENDAR_AUTOMATION_KEYWORDS)
    has_calendar_reference = CALENDAR_REFERENCE_PATTERN.search(message) is not None or TIME_FRAGMENT_PATTERN.search(message) is not None
    has_calendar_context = has_calendar_keyword or has_calendar_reference
    has_gmail_keyword = any(keyword in lowered for keyword in GMAIL_AUTOMATION_KEYWORDS) or EMAIL_ADDRESS_PATTERN.search(message) is not None

    if any(keyword in message for keyword in CALENDAR_UPDATE_KEYWORDS) and has_calendar_context:
        return "calendar_update"
    if any(keyword in message for keyword in CALENDAR_CREATE_KEYWORDS) and has_calendar_context:
        return "calendar_create"
    if has_calendar_context and any(keyword in message for keyword in CALENDAR_DELETE_KEYWORDS):
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

    if any(keyword in lowered for keyword in MACOS_NOTE_KEYWORDS) and any(
        keyword in message for keyword in MACOS_NOTE_CREATE_KEYWORDS
    ):
        return "macos_note_create"
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
    structured_extraction: StructuredExtraction | None = None,
) -> dict[str, str | None]:
    extraction = structured_extraction or extract_structured_request(message, channel)
    intent = intent_override or extraction.intent

    if intent == "calendar_summary" and settings.n8n_webhook_path:
        reply = run_n8n_automation(message, channel, session_id, user_id, settings.n8n_webhook_path)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": None}
        fallback_reply, _ = generate_local_reply(message, channel)
        return {"reply": fallback_reply, "route": "n8n_fallback", "action_type": None}

    if intent in {"calendar_create", "calendar_update", "calendar_delete"}:
        parsed = _calendar_payload_to_request(extraction.calendar, intent) if extraction.calendar else parse_calendar_request(message, intent)
        if parsed is None:
            example = (
                "내일 오후 3시에 치과 일정 추가해줘"
                if intent == "calendar_create"
                else "내일 오후 4시 치과 일정 변경해줘"
                if intent == "calendar_update"
                else "오늘 06:00-07:00 피자 시키기 일정 삭제해줘"
            )
            guidance = "삭제할 일정의 제목이나 시간을 더 구체적으로 알려주세요. " if intent == "calendar_delete" else ""
            return {
                "reply": f"일정 요청을 이해하지 못했습니다. {guidance}예: {example}",
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
        parsed = _mail_payload_to_compose_request(extraction.mail, intent) if extraction.mail else parse_gmail_compose_request(message, intent)
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
        parsed = _mail_payload_to_reply_request(extraction.mail, intent) if extraction.mail else parse_gmail_reply_request(message, intent)
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

    if intent == "macos_note_create":
        parsed = parse_macos_note_request(message)
        if parsed is None:
            return {
                "reply": "macOS 메모 요청을 이해하지 못했습니다. 예: 메모에 제목 주간 점검 내용 브라우저 러너와 Slack 상태 확인 저장해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        if not approval_granted:
            return {
                "reply": "macOS 메모 생성 요청입니다. 승인 후 AppleScript로 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        reply = run_macos_automation(message, channel, session_id, user_id, "macos/notes", parsed)
        if reply is not None:
            return {"reply": reply, "route": "macos", "action_type": intent}
        return {
            "reply": "승인된 macOS 메모 실행에 실패했습니다. 호스트 macOS runner 실행 상태와 Notes 자동화 권한을 확인하세요.",
            "route": "macos_fallback",
            "action_type": intent,
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


def run_macos_automation(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None,
    endpoint_path: str,
    extra_payload: dict[str, str],
) -> str | None:
    endpoint = f"{settings.macos_automation_base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"
    payload = {
        "message": message,
        "channel": channel,
        "session_id": session_id,
        "user_id": user_id,
    }
    payload.update(extra_payload)

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            if isinstance(body.get("reply"), str) and body["reply"].strip():
                return body["reply"].strip()
            if isinstance(body.get("message"), str) and body["message"].strip():
                return body["message"].strip()
        return "macOS 자동화 작업을 실행했습니다."
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
    normalized_body = _normalize_gmail_reply_body(body)
    if not normalized_body:
        return None

    result = {
        "reply_mode": "thread" if intent == "gmail_thread_reply" else "reply",
        "message": normalized_body,
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


def parse_macos_note_request(message: str) -> dict[str, str] | None:
    title = _extract_labeled_segment(
        message,
        labels=("제목", "title"),
        stop_labels=("내용", "본문", "message", "폴더", "folder", *MACOS_NOTE_ACTION_STOP_LABELS),
    )
    body = _extract_labeled_segment(
        message,
        labels=("내용", "본문", "message"),
        stop_labels=("폴더", "folder", *MACOS_NOTE_ACTION_STOP_LABELS),
    )
    folder = _extract_labeled_segment(
        message,
        labels=("폴더", "folder"),
        stop_labels=MACOS_NOTE_ACTION_STOP_LABELS,
    )

    if not title or not body:
        return None

    result = {
        "title": title,
        "body": body,
    }
    if folder:
        result["folder"] = folder
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
    numeric_month_day = re.search(r"(?<![\d:])(\d{1,2})[./-](\d{1,2})(?![\d:])", message)
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
    working = re.sub(r"(?:^|\s)내용(?:을|를|이|가|은|는|도|만)?(?=\s|$)", " ", working)
    working = re.sub(r"\s+", " ", working).strip(" .,")
    tokens = [token.strip(" .,") for token in working.split()]
    filtered_tokens = [
        token
        for token in tokens
        if token and token not in CALENDAR_TITLE_STOP_TOKENS and not CALENDAR_TITLE_NOISE_PATTERN.fullmatch(token)
    ]
    return " ".join(filtered_tokens)


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