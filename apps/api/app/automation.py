import httpx
import logging
import re
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.llm import generate_structured_extraction
from app.llm import generate_local_reply
from app.schemas import CalendarExtractionPayload
from app.schemas import ExtractionReference
from app.schemas import MailExtractionPayload
from app.schemas import NoteExtractionPayload
from app.schemas import StructuredExtraction
from app.skills.registry import classify_intent_from_registry
from app.skills.registry import ensure_initialized as _ensure_skills

logger = logging.getLogger("uvicorn.error")


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
MACOS_REMINDER_KEYWORDS = ("미리알림", "리마인더", "reminder", "할일", "할 일")
MACOS_REMINDER_CREATE_KEYWORDS = ("추가", "등록", "만들", "생성", "작성")
MACOS_VOLUME_KEYWORDS = ("볼륨", "volume", "소리", "음량")
MACOS_DARKMODE_KEYWORDS = ("다크모드", "다크 모드", "라이트모드", "라이트 모드", "dark mode")
MACOS_FINDER_KEYWORDS = ("파인더", "finder", "폴더 열")
VOLUME_LEVEL_PATTERN = re.compile(r"(\d{1,3})\s*(?:%|퍼센트)?")
WEB_SEARCH_KEYWORDS = ("검색", "찾아줘", "찾아 줘", "search", "가격", "환율", "주가", "날씨")

EMAIL_ADDRESS_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_PATTERN = re.compile(r"https?://[^\s,]+", re.IGNORECASE)
TIME_FRAGMENT_PATTERN = re.compile(
    r"(?:오전|오후)?\s*\d{1,2}(?:(?::\s*\d{2})|\s*시(?:\s*\d{1,2}\s*분?)?)\s*(?:반)?"
)
THREAD_ID_PATTERN = re.compile(r"(?:thread|스레드)\s*(?:id)?\s*[:=]?\s*([A-Za-z0-9_-]+)", re.IGNORECASE)
MESSAGE_ID_PATTERN = re.compile(r"(?:message|메시지|메일)\s*(?:id)?\s*[:=]?\s*([A-Za-z0-9_-]{10,})", re.IGNORECASE)

REFERENCE_MESSAGE_HINTS = (
    "그 일정",
    "그 메일",
    "그 답장",
    "그 초안",
    "그대로",
    "그거",
    "그걸",
    "그것",
    "방금",
    "앞에",
    "이전",
    "아까",
    "해당",
    "위에",
    "위의",
    "첫 번째",
    "첫번째",
    "두 번째",
    "두번째",
    "세 번째",
    "세번째",
    "네 번째",
    "네번째",
    "다섯 번째",
    "다섯번째",
    "1번",
    "2번",
    "3번",
    "4번",
    "5번",
)

ORDINAL_PATTERNS = re.compile(
    r"(?:(?P<korean>첫|두|세|네|다섯)\s*번째)|"
    r"(?:(?P<digit>\d+)\s*번(?:째)?)",
)

KOREAN_ORDINAL_MAP = {
    "첫": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
}

MEMORY_CUE_PHRASES = (
    "기억해줘",
    "기억해 둬",
    "기억해",
    "참고해줘",
    "참고해",
    "잊지 마",
    "다음부터",
    "앞으로",
    "항상",
)

MEMORY_STYLE_HINTS = (
    "답변",
    "응답",
    "요약",
    "말투",
    "톤",
    "형식",
    "불릿",
    "표로",
    "짧게",
    "길게",
    "핵심만",
    "존댓말",
    "반말",
)

MEMORY_PROFILE_HINTS = (
    "저는",
    "나는",
    "전 ",
    "내 이름",
    "제 이름",
    "내 직함",
    "우리 팀",
    "제가 담당",
)

MEMORY_SECRET_HINTS = (
    "비밀번호",
    "password",
    "otp",
    "인증번호",
    "access token",
    "api key",
    "secret",
)

ACTION_LABELS = {
    "calendar_create": "생성",
    "calendar_update": "변경",
    "calendar_delete": "삭제",
    "gmail_draft": "초안 작성",
    "gmail_send": "발송",
    "gmail_reply": "회신",
    "gmail_thread_reply": "thread 이어쓰기",
    "macos_note_create": "macOS 메모 생성",
    "macos_reminder_create": "macOS 미리알림 추가",
    "macos_volume_set": "macOS 볼륨 변경",
    "macos_darkmode_toggle": "macOS 다크모드 전환",
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


# ---------------------------------------------------------------------------
# Summary/List 시간 범위 파싱
# ---------------------------------------------------------------------------

_SUMMARY_TIME_REFS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"오늘"), "today"),
    (re.compile(r"내일"), "tomorrow"),
    (re.compile(r"모레"), "day_after_tomorrow"),
    (re.compile(r"이번\s*주"), "this_week"),
    (re.compile(r"다음\s*주"), "next_week"),
    (re.compile(r"지난\s*주|저번\s*주"), "last_week"),
    (re.compile(r"이번\s*달"), "this_month"),
    (re.compile(r"다음\s*달"), "next_month"),
]


def _parse_summary_time_range(message: str) -> tuple[str | None, str | None]:
    """메시지에서 시간 참조를 파싱하여 (timeMin, timeMax) ISO 문자열을 반환한다."""
    tz = ZoneInfo(settings.calendar_timezone if hasattr(settings, "calendar_timezone") else "Asia/Seoul")
    now = datetime.now(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for pattern, ref_type in _SUMMARY_TIME_REFS:
        if pattern.search(message) is None:
            continue
        if ref_type == "today":
            return today_start.isoformat(), (today_start + timedelta(days=1)).isoformat()
        elif ref_type == "tomorrow":
            t = today_start + timedelta(days=1)
            return t.isoformat(), (t + timedelta(days=1)).isoformat()
        elif ref_type == "day_after_tomorrow":
            t = today_start + timedelta(days=2)
            return t.isoformat(), (t + timedelta(days=1)).isoformat()
        elif ref_type == "this_week":
            week_start = today_start - timedelta(days=now.weekday())
            return week_start.isoformat(), (week_start + timedelta(days=7)).isoformat()
        elif ref_type == "next_week":
            week_start = today_start + timedelta(days=7 - now.weekday())
            return week_start.isoformat(), (week_start + timedelta(days=7)).isoformat()
        elif ref_type == "last_week":
            week_start = today_start - timedelta(days=now.weekday() + 7)
            return week_start.isoformat(), (week_start + timedelta(days=7)).isoformat()
        elif ref_type == "this_month":
            month_start = today_start.replace(day=1)
            if now.month == 12:
                month_end = month_start.replace(year=now.year + 1, month=1)
            else:
                month_end = month_start.replace(month=now.month + 1)
            return month_start.isoformat(), month_end.isoformat()
        elif ref_type == "next_month":
            if now.month == 12:
                month_start = today_start.replace(year=now.year + 1, month=1, day=1)
            else:
                month_start = today_start.replace(month=now.month + 1, day=1)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1)
            return month_start.isoformat(), month_end.isoformat()
    return None, None


def _build_gmail_search_query(message: str) -> str | None:
    """Gmail 요약 쿼리에서 검색 조건을 추출한다."""
    msg = re.sub(r"\s+", " ", message).strip().lower()
    parts: list[str] = []

    # 시간 참조
    if "오늘" in msg:
        parts.append("newer_than:1d")
    elif "이번 주" in msg or "이번주" in msg:
        parts.append("newer_than:7d")
    elif "지난 주" in msg or "저번 주" in msg or "지난주" in msg or "저번주" in msg:
        parts.append("newer_than:14d older_than:7d")
    elif "이번 달" in msg or "이번달" in msg:
        parts.append("newer_than:30d")
    elif "최근" in msg:
        parts.append("newer_than:3d")

    # 발신자 참조
    sender_match = re.search(r"(\S+)(?:에게서|한테서|로부터|가 보낸|이 보낸)", msg)
    if sender_match:
        parts.append(f"from:{sender_match.group(1)}")

    # 키워드 참조
    subject_match = re.search(r"(?:제목|주제|subject)[\s:：]*(\S+)", msg)
    if subject_match:
        parts.append(f'subject:"{subject_match.group(1)}"')

    return " ".join(parts) if parts else None
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
    elif intent == "calendar_summary":
        time_min, time_max = _parse_summary_time_range(message)
        if time_min or time_max:
            calendar_payload = CalendarExtractionPayload(
                searchTimeMin=time_min,
                searchTimeMax=time_max,
            )
    elif intent == "gmail_summary":
        search_query = _build_gmail_search_query(message)
        if search_query:
            mail_payload = MailExtractionPayload(searchQuery=search_query)

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


def apply_reference_context(
    extraction: StructuredExtraction,
    previous_extraction: StructuredExtraction | None,
    last_candidates: list[dict[str, str]] | None = None,
) -> StructuredExtraction:
    # 1. 순서 참조 ("두 번째", "1번") + 후보 목록이 있으면 후보 선택 적용
    ordinal_idx = parse_ordinal_index(extraction.raw_message)
    if ordinal_idx is not None and last_candidates and 0 <= ordinal_idx < len(last_candidates):
        candidate = last_candidates[ordinal_idx]
        candidate_label = candidate.get("label", candidate.get("raw", ""))
        extraction = _apply_candidate_selection(extraction, candidate_label, ordinal_idx, previous_extraction)

    if previous_extraction is None:
        return extraction

    should_backfill = extraction.needs_clarification or bool(extraction.missing_fields) or _has_reference_signal(extraction.raw_message)
    if extraction.domain != previous_extraction.domain or not should_backfill:
        # 도메인이 달라도 후보 선택이면 이전 도메인을 계승
        if ordinal_idx is not None and last_candidates and extraction.domain in {"chat", "unknown"}:
            extraction = _inherit_domain_from_previous(extraction, previous_extraction)
            return extraction
        return extraction

    if extraction.domain == "calendar":
        return _apply_calendar_reference_context(extraction, previous_extraction)
    if extraction.domain == "mail":
        return _apply_mail_reference_context(extraction, previous_extraction)
    if extraction.domain == "note":
        return _apply_note_reference_context(extraction, previous_extraction)
    return extraction


def _apply_candidate_selection(
    extraction: StructuredExtraction,
    candidate_label: str,
    index: int,
    previous_extraction: StructuredExtraction | None,
) -> StructuredExtraction:
    """후보 선택 시 선택된 항목의 라벨을 extraction payload에 주입한다."""
    ref = ExtractionReference(
        referenceType="candidate_selection",
        referenceId=str(index),
        label=candidate_label,
        score=0.9,
    )
    extraction.references = [ref] + list(extraction.references)
    extraction.metadata = {
        **dict(extraction.metadata),
        "candidate_selected": True,
        "candidate_index": index,
        "candidate_label": candidate_label,
    }

    # 도메인별 payload에 후보 라벨 주입
    if extraction.domain == "calendar" and extraction.calendar:
        if not extraction.calendar.title or not extraction.calendar.search_title:
            extraction.calendar.title = extraction.calendar.title or candidate_label
            extraction.calendar.search_title = extraction.calendar.search_title or candidate_label
    elif extraction.domain == "mail" and extraction.mail:
        if not extraction.mail.subject:
            extraction.mail.subject = candidate_label
        if not extraction.mail.search_query:
            extraction.mail.search_query = candidate_label
    elif extraction.domain == "note" and extraction.note:
        if not extraction.note.title:
            extraction.note.title = candidate_label

    # needs_clarification 해제
    if extraction.needs_clarification:
        extraction.needs_clarification = False
        extraction.missing_fields = [f for f in extraction.missing_fields if f not in {"title", "subject", "target", "date_or_time"}]
    return extraction


def _inherit_domain_from_previous(
    extraction: StructuredExtraction,
    previous_extraction: StructuredExtraction,
) -> StructuredExtraction:
    """도메인이 chat/unknown이지만 이전 도메인을 계승하여 후보 선택을 완성한다."""
    extraction.domain = previous_extraction.domain
    extraction.action = previous_extraction.action
    extraction.intent = previous_extraction.intent
    extraction.confidence = max(extraction.confidence, 0.7)
    return extraction


def _has_reference_signal(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", message).strip().lower()
    return any(hint in normalized for hint in REFERENCE_MESSAGE_HINTS)


def parse_ordinal_index(message: str) -> int | None:
    """메시지에서 순서 참조(1번, 두 번째 등)를 파싱해 0-based 인덱스를 반환한다."""
    m = ORDINAL_PATTERNS.search(message)
    if m is None:
        return None
    korean = m.group("korean")
    if korean:
        return KOREAN_ORDINAL_MAP.get(korean, 1) - 1
    digit = m.group("digit")
    if digit:
        idx = int(digit)
        if 1 <= idx <= 20:
            return idx - 1
    return None


# ---------------------------------------------------------------------------
# 어시스턴트 응답에서 후보 목록 추출
# ---------------------------------------------------------------------------

_NUMBERED_ITEM_PATTERN = re.compile(
    r"^\s*(?:(?P<num>\d+)[.)\]]\s*|[-•]\s*)"
    r"(?P<text>.+)$",
    re.MULTILINE,
)


def extract_candidates_from_reply(reply: str, route: str) -> list[dict[str, str]]:
    """어시스턴트 응답 텍스트에서 번호가 매겨진 항목 목록을 후보로 추출한다.

    Returns:
        [{"index": 0, "label": "...", "raw": "..."}, ...]
    """
    if route not in {"n8n", "n8n_fallback", "local_llm", "web_search"}:
        return []

    items = []
    for m in _NUMBERED_ITEM_PATTERN.finditer(reply):
        text = m.group("text").strip()
        if len(text) < 3:
            continue
        items.append({
            "index": len(items),
            "label": text[:120],
            "raw": text,
        })

    # 최소 2개 이상일 때만 후보 목록으로 취급
    if len(items) < 2:
        return []
    return items[:20]


def _reference_metadata(previous_extraction: StructuredExtraction, label: str | None = None) -> dict[str, object]:
    return {
        "reference_context_applied": True,
        "reference_source_intent": previous_extraction.intent,
        "reference_source_label": label or previous_extraction.intent,
    }


def _build_reference_item(previous_extraction: StructuredExtraction, label: str | None = None) -> ExtractionReference:
    return ExtractionReference(
        referenceType="session_last_extraction",
        referenceId=previous_extraction.intent,
        label=label or previous_extraction.intent,
        score=0.8,
    )


def _apply_calendar_reference_context(
    extraction: StructuredExtraction,
    previous_extraction: StructuredExtraction,
) -> StructuredExtraction:
    previous = previous_extraction.calendar
    if previous is None:
        return extraction

    current = extraction.calendar or CalendarExtractionPayload()
    merged_calendar = CalendarExtractionPayload(
        title=current.title or previous.title or previous.search_title,
        searchTitle=current.search_title or previous.search_title or previous.title,
        date=current.date or previous.date,
        startAt=current.start_at or previous.start_at,
        endAt=current.end_at or previous.end_at,
        searchTimeMin=current.search_time_min or previous.search_time_min or previous.start_at,
        searchTimeMax=current.search_time_max or previous.search_time_max or previous.end_at,
        timezone=current.timezone or previous.timezone,
    )

    missing_fields = list(extraction.missing_fields)
    if merged_calendar.search_title and (merged_calendar.search_time_min or merged_calendar.start_at):
        missing_fields = [field for field in missing_fields if field not in {"title", "date_or_time", "date", "time"}]

    return extraction.model_copy(
        update={
            "calendar": merged_calendar,
            "needs_clarification": bool(missing_fields),
            "missing_fields": missing_fields,
            "references": extraction.references or [_build_reference_item(previous_extraction, merged_calendar.search_title or merged_calendar.title)],
            "metadata": {
                **dict(extraction.metadata),
                **_reference_metadata(previous_extraction, merged_calendar.search_title or merged_calendar.title),
            },
        }
    )


def _apply_mail_reference_context(
    extraction: StructuredExtraction,
    previous_extraction: StructuredExtraction,
) -> StructuredExtraction:
    previous = previous_extraction.mail
    if previous is None:
        return extraction

    current = extraction.mail or MailExtractionPayload()
    merged_mail = MailExtractionPayload(
        replyMode=current.reply_mode or previous.reply_mode,
        recipients=current.recipients or previous.recipients,
        cc=current.cc or previous.cc,
        bcc=current.bcc or previous.bcc,
        sender=current.sender or previous.sender,
        subject=current.subject or previous.subject,
        body=current.body or previous.body,
        threadReference=current.thread_reference or previous.thread_reference,
        messageReference=current.message_reference or previous.message_reference,
        searchQuery=current.search_query or previous.search_query,
        attachmentUrls=current.attachment_urls or previous.attachment_urls,
    )

    missing_fields = list(extraction.missing_fields)
    if extraction.intent in {"gmail_draft", "gmail_send"} and merged_mail.recipients and merged_mail.subject and merged_mail.body:
        missing_fields = [field for field in missing_fields if field not in {"recipients", "subject", "body"}]
    if extraction.intent in {"gmail_reply", "gmail_thread_reply"} and merged_mail.body and (
        merged_mail.thread_reference or merged_mail.message_reference or merged_mail.search_query
    ):
        missing_fields = [field for field in missing_fields if field not in {"message", "target"}]

    return extraction.model_copy(
        update={
            "mail": merged_mail,
            "needs_clarification": bool(missing_fields),
            "missing_fields": missing_fields,
            "references": extraction.references or [_build_reference_item(previous_extraction, merged_mail.subject)],
            "metadata": {
                **dict(extraction.metadata),
                **_reference_metadata(previous_extraction, merged_mail.subject),
            },
        }
    )


def _apply_note_reference_context(
    extraction: StructuredExtraction,
    previous_extraction: StructuredExtraction,
) -> StructuredExtraction:
    previous = previous_extraction.note
    if previous is None:
        return extraction

    current = extraction.note or NoteExtractionPayload()
    merged_note = NoteExtractionPayload(
        title=current.title or previous.title,
        body=current.body or previous.body,
        folder=current.folder or previous.folder,
    )
    missing_fields = list(extraction.missing_fields)
    if merged_note.title and merged_note.body:
        missing_fields = [field for field in missing_fields if field not in {"title", "body"}]

    return extraction.model_copy(
        update={
            "note": merged_note,
            "needs_clarification": bool(missing_fields),
            "missing_fields": missing_fields,
            "references": extraction.references or [_build_reference_item(previous_extraction, merged_note.title)],
            "metadata": {
                **dict(extraction.metadata),
                **_reference_metadata(previous_extraction, merged_note.title),
            },
        }
    )


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
    _ensure_skills()
    registry_result = classify_intent_from_registry(message)
    if registry_result is not None:
        return registry_result
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

    if any(keyword in lowered for keyword in MACOS_REMINDER_KEYWORDS) and any(
        keyword in lowered for keyword in MACOS_REMINDER_CREATE_KEYWORDS
    ):
        return "macos_reminder_create"

    if any(keyword in lowered for keyword in MACOS_VOLUME_KEYWORDS):
        # "볼륨 확인"류는 get, 숫자가 있으면 set
        if VOLUME_LEVEL_PATTERN.search(message):
            return "macos_volume_set"
        return "macos_volume_get"

    if any(keyword in lowered for keyword in MACOS_DARKMODE_KEYWORDS):
        return "macos_darkmode_toggle"

    if any(keyword in lowered for keyword in MACOS_FINDER_KEYWORDS):
        return "macos_finder_open"

    if any(keyword in lowered for keyword in WEB_SEARCH_KEYWORDS):
        return "web_search"

    return "chat"


def should_route_to_automation(message: str) -> bool:
    return classify_message_intent(message) != "chat"


def extract_user_memory_candidates(message: str) -> list[dict[str, str]]:
    normalized = re.sub(r"\s+", " ", message).strip()
    lowered = normalized.lower()
    if len(normalized) < 8:
        return []
    if any(secret_hint in lowered for secret_hint in MEMORY_SECRET_HINTS):
        return []
    if not any(cue in normalized for cue in MEMORY_CUE_PHRASES):
        return []

    content = normalized
    content = re.sub(r"^(?:앞으로|다음부터|항상)\s*", "", content).strip()
    content = re.sub(r"\s*(?:기억해줘|기억해 둬|기억해|참고해줘|참고해|잊지 마)\s*[.!]?$", "", content).strip()
    content = content.strip(" .,")
    if len(content) < 6 or len(content) > 240:
        return []

    category = "general"
    if any(hint in normalized for hint in MEMORY_STYLE_HINTS):
        category = "preference"
    elif any(hint in normalized for hint in MEMORY_PROFILE_HINTS):
        category = "profile"

    return [{"category": category, "content": content, "source": "auto"}]


def process_message(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
    intent_override: str | None = None,
    approval_granted: bool = False,
    structured_extraction: StructuredExtraction | None = None,
    memory_context: list[dict[str, str]] | None = None,
    provider_hint: str | None = None,
) -> dict[str, str | None]:
    """메시지를 처리한다. LangGraph 워크플로가 사용 가능하면 우선 사용한다."""
    try:
        from app.graph.workflow import run_workflow
        return run_workflow(
            message=message,
            channel=channel,
            session_id=session_id,
            user_id=user_id,
            intent_override=intent_override,
            approval_granted=approval_granted,
            memory_context=memory_context,
            structured_extraction=structured_extraction,
            provider_hint=provider_hint,
        )
    except Exception as exc:
        logger.warning("LangGraph workflow failed, falling back to legacy: %s", exc)
        return _process_message_legacy(
            message=message,
            channel=channel,
            session_id=session_id,
            user_id=user_id,
            intent_override=intent_override,
            approval_granted=approval_granted,
            structured_extraction=structured_extraction,
            memory_context=memory_context,
        )


def _process_message_legacy(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
    intent_override: str | None = None,
    approval_granted: bool = False,
    structured_extraction: StructuredExtraction | None = None,
    memory_context: list[dict[str, str]] | None = None,
) -> dict[str, str | None]:
    extraction = structured_extraction or extract_structured_request(message, channel)
    intent = intent_override or extraction.intent

    if intent == "calendar_summary" and settings.n8n_webhook_path:
        reply = run_n8n_automation(message, channel, session_id, user_id, settings.n8n_webhook_path)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": None}
        fallback_reply, _ = generate_local_reply(message, channel, memory_context)
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

    if intent == "macos_reminder_create":
        parsed = parse_macos_reminder_request(message)
        if parsed is None:
            return {
                "reply": "미리알림 요청을 이해하지 못했습니다. 예: 미리알림에 장보기 추가해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        if not approval_granted:
            return {
                "reply": "macOS 미리알림 추가 요청입니다. 승인 후 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        reply = run_macos_automation(message, channel, session_id, user_id, "macos/reminders", parsed)
        if reply is not None:
            return {"reply": reply, "route": "macos", "action_type": intent}
        return {
            "reply": "macOS 미리알림 실행에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
            "route": "macos_fallback",
            "action_type": intent,
        }

    if intent == "macos_volume_get":
        reply = run_macos_get("macos/system/volume")
        if reply is not None:
            return {"reply": reply, "route": "macos", "action_type": intent}
        return {
            "reply": "macOS 볼륨 확인에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
            "route": "macos_fallback",
            "action_type": intent,
        }

    if intent == "macos_volume_set":
        parsed = parse_macos_volume_set_request(message)
        if parsed is None:
            return {
                "reply": "볼륨 값을 이해하지 못했습니다. 예: 볼륨 50으로 설정해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        if not approval_granted:
            return {
                "reply": f"macOS 볼륨을 {parsed['level']}%로 변경하는 요청입니다. 승인 후 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        reply = run_macos_automation(message, channel, session_id, user_id, "macos/system/volume", parsed)
        if reply is not None:
            return {"reply": reply, "route": "macos", "action_type": intent}
        return {
            "reply": "macOS 볼륨 변경에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
            "route": "macos_fallback",
            "action_type": intent,
        }

    if intent == "macos_darkmode_toggle":
        if not approval_granted:
            return {
                "reply": "macOS 다크모드 전환 요청입니다. 승인 후 실행합니다.",
                "route": "approval_required",
                "action_type": intent,
            }
        reply = run_macos_automation(message, channel, session_id, user_id, "macos/system/darkmode", {})
        if reply is not None:
            return {"reply": reply, "route": "macos", "action_type": intent}
        return {
            "reply": "macOS 다크모드 전환에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
            "route": "macos_fallback",
            "action_type": intent,
        }

    if intent == "macos_finder_open":
        parsed = parse_macos_finder_open_request(message)
        if parsed is None:
            return {
                "reply": "Finder에서 열 경로를 이해하지 못했습니다. 예: ~/Documents 폴더 열어줘",
                "route": "validation_error",
                "action_type": intent,
            }
        reply = run_macos_automation(message, channel, session_id, user_id, "macos/finder/open", parsed)
        if reply is not None:
            return {"reply": reply, "route": "macos", "action_type": intent}
        return {
            "reply": "Finder 폴더 열기에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
            "route": "macos_fallback",
            "action_type": intent,
        }

    if intent == "web_search":
        from app.search import run_web_search, format_search_results_for_llm

        search_result = run_web_search(message)
        if search_result.get("error"):
            # 검색 불가 시 로컬 LLM에 직접 위임
            reply, route = generate_local_reply(message, channel, memory_context)
            return {"reply": reply, "route": route, "action_type": None}
        context_text = format_search_results_for_llm(search_result)
        search_memory = [{"category": "search_context", "content": context_text, "source": "web_search"}]
        combined_memory = (memory_context or []) + search_memory
        reply, route = generate_local_reply(
            f"다음 검색 결과를 바탕으로 사용자 질문에 답변해줘.\n\n{context_text}\n\n사용자 질문: {message}",
            channel,
            combined_memory,
        )
        return {"reply": reply, "route": "web_search", "action_type": "web_search"}

    reply, route = generate_local_reply(message, channel, memory_context)
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


def run_n8n_automation_raw(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
    webhook_path: str | None = None,
    extra_payload: dict[str, str] | None = None,
) -> dict | None:
    """n8n 자동화를 호출하고 응답 JSON 딕셔너리 전체를 반환한다."""
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
            return body
        return None
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


def parse_macos_reminder_request(message: str) -> dict[str, str] | None:
    """미리알림 요청에서 이름/메모/목록 세그먼트를 추출한다."""
    action_stop = (*MACOS_REMINDER_CREATE_KEYWORDS, *MACOS_NOTE_ACTION_STOP_LABELS, "추가해줘", "추가해 줘", "등록해줘", "만들어줘")
    name = _extract_labeled_segment(
        message,
        labels=("이름", "name", "제목", "title"),
        stop_labels=("메모", "노트", "note", "목록", "list", *action_stop),
    )
    # 라벨이 없으면 미리알림 키워드와 액션 키워드 사이의 텍스트를 이름으로 간주
    if not name:
        lowered = message.lower()
        # 미리알림 키워드 뒤, 액션 키워드 앞 사이의 텍스트
        for rk in MACOS_REMINDER_KEYWORDS:
            rk_lower = rk.lower()
            if rk_lower in lowered:
                start = lowered.index(rk_lower) + len(rk_lower)
                tail = message[start:].strip()
                # 조사 제거
                tail = re.sub(r"^[에의으로]\s*", "", tail)
                # 액션 키워드 앞까지
                for ak in MACOS_REMINDER_CREATE_KEYWORDS:
                    ak_idx = tail.find(ak)
                    if ak_idx > 0:
                        tail = tail[:ak_idx].strip()
                        break
                tail = tail.rstrip("해줘 줘요 해 요 좀 부탁")
                if tail:
                    name = tail
                    break
    if not name:
        return None
    note = _extract_labeled_segment(
        message,
        labels=("메모", "노트", "note"),
        stop_labels=("목록", "list", *action_stop),
    ) or ""
    list_name = _extract_labeled_segment(
        message,
        labels=("목록", "list"),
        stop_labels=action_stop,
    ) or "Reminders"
    return {"name": name, "note": note, "list_name": list_name}


def parse_macos_volume_set_request(message: str) -> dict[str, int] | None:
    """볼륨 설정 요청에서 레벨(0-100)을 추출한다."""
    match = VOLUME_LEVEL_PATTERN.search(message)
    if not match:
        return None
    level = int(match.group(1))
    if level < 0 or level > 100:
        return None
    return {"level": level}


def parse_macos_finder_open_request(message: str) -> dict[str, str] | None:
    """Finder 열기 요청에서 경로를 추출한다."""
    path = _extract_labeled_segment(
        message,
        labels=("경로", "path"),
        stop_labels=("폴더", *MACOS_NOTE_ACTION_STOP_LABELS),
    )
    if path:
        if ".." in path:
            return None
        return {"path": path}
    # ~/xxx 또는 /xxx 패턴 탐색
    path_match = re.search(r"((?:~|/)[^\s,]+)", message)
    if path_match:
        candidate = path_match.group(1)
        if ".." in candidate:
            return None
        return {"path": candidate}
    return None


def run_macos_get(endpoint_path: str) -> str | None:
    """macOS runner GET 엔드포인트를 호출한다."""
    endpoint = f"{settings.macos_automation_base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(endpoint)
            response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            if isinstance(body.get("reply"), str) and body["reply"].strip():
                return body["reply"].strip()
        return "macOS 정보를 조회했습니다."
    except Exception:
        return None


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