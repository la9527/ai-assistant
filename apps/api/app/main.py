import hashlib
import hmac
import json
import logging
import re
import time
from urllib.parse import parse_qs

from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request

import httpx

from app.automation import classify_message_intent
from app.automation import extract_structured_request
from app.automation import process_message
from app.config import settings
from app.db import Base
from app.db import engine
from app.db import get_db
from app.db import SessionLocal
from app.llm import warm_local_llm
from app.models import ApprovalTicket
from app.models import AssistantSession
from app.models import TaskRun
from app.repositories import create_session_message
from app.repositories import create_approval_ticket
from app.repositories import create_session
from app.repositories import create_task_run
from app.repositories import get_approval_ticket
from app.repositories import get_latest_task_run
from app.repositories import get_session_by_id
from app.repositories import get_session_state
from app.repositories import get_task_run
from app.repositories import list_session_messages
from app.repositories import update_task_run_status
from app.repositories import update_approval_ticket_status
from app.repositories import update_session_message
from app.repositories import upsert_session_state
from app.schemas import ApprovalActionRequest
from app.schemas import ApprovalTicketResponse
from app.schemas import BrowserReadRequest
from app.schemas import BrowserReadResponse
from app.schemas import ChatRequest
from app.schemas import ChatResponse
from app.schemas import HealthResponse
from app.schemas import KakaoBasicCard
from app.schemas import KakaoBasicCardOutput
from app.schemas import KakaoButton
from app.schemas import KakaoQuickReply
from app.schemas import KakaoSimpleText
from app.schemas import KakaoSimpleTextOutput
from app.schemas import KakaoTemplate
from app.schemas import KakaoThumbnail
from app.schemas import KakaoWebhookResponse
from app.schemas import KakaoWebhookUtterance
from app.schemas import SessionResponse
from app.schemas import SessionMessageResponse
from app.schemas import SessionStateResponse
from app.schemas import StructuredExtraction
from app.schemas import TaskResponse


app = FastAPI(title="AI Assistant API", version="0.1.0")

logger = logging.getLogger("uvicorn.error")

SLACK_CHANNEL_NAME_CACHE: dict[str, str] = {}

APPROVE_PATTERN = re.compile(r"^(승인|approve)\s+([a-zA-Z0-9-]+)$", re.IGNORECASE)
REJECT_PATTERN = re.compile(r"^(거절|reject)\s+([a-zA-Z0-9-]+)$", re.IGNORECASE)
KAKAO_BASIC_CARD_DESCRIPTION_LIMIT = 230
KAKAO_SIMPLE_TEXT_LIMIT = 1000
KAKAO_BASIC_CARD_THUMBNAIL_URL = "https://dummyimage.com/640x360/0f172a/ffffff.png&text=AI+Assistant"
KAKAO_BASIC_CARD_THUMBNAIL_ALT = "AI Assistant"
KAKAO_CALLBACK_PENDING_MESSAGE = "요청을 접수했습니다. 결과를 준비 중입니다."
KAKAO_CALLBACK_FAILURE_MESSAGE = "요청 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요."
SLACK_PENDING_MESSAGE = "요청을 접수했습니다. 작업이 끝나면 결과를 이어서 알려드리겠습니다."
SLACK_FAILURE_MESSAGE = "요청 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요."

KAKAO_SUGGESTION_PRESETS: dict[str, list[tuple[str, str]]] = {
    "general": [
        ("일정 요약", "오늘 일정 요약해줘"),
        ("메일 요약", "최근 메일 요약해줘"),
        ("메모 작성", "메모에 제목 오늘 할 일 내용 일정과 메일 확인 저장해줘"),
    ],
    "calendar": [
        ("오늘 일정", "오늘 일정 요약해줘"),
        ("내일 일정", "내일 일정 요약해줘"),
        ("일정 삭제", "내일 오후 3시 회의 일정 삭제해줘"),
    ],
    "gmail_summary": [
        ("메일 요약", "최근 메일 요약해줘"),
        ("메일 초안", "test@example.com로 제목 안부, 내용 안녕하세요 메일 초안 작성해줘"),
        ("메일 회신", "제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘"),
    ],
    "gmail_action": [
        ("최근 메일", "최근 메일 요약해줘"),
        ("메일 초안", "test@example.com로 제목 안부, 내용 안녕하세요 메일 초안 작성해줘"),
        ("첨부 회신", "제목 AI Assistant Gmail 발송 테스트 내용 첨부 확인 부탁드립니다 첨부 https://raw.githubusercontent.com/github/gitignore/main/README.md 메일에 답장해줘"),
    ],
    "notes": [
        ("메모 작성", "메모에 제목 오늘 할 일 내용 일정과 메일 확인 저장해줘"),
        ("일정 요약", "오늘 일정 요약해줘"),
        ("메일 요약", "최근 메일 요약해줘"),
    ],
}


def _format_kakao_display_text(text: str) -> str:
    formatted = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    formatted = re.sub(r"\s*/\s*(?=(?:\d+\.|[-*]))", "\n\n", formatted)
    formatted = re.sub(r"(?<=요약입니다\.)\s+", "\n\n", formatted)
    formatted = re.sub(r"(?<=[.!?])\s+(?=\d+\.)", "\n\n", formatted)
    formatted = re.sub(r"[ \t]+", " ", formatted)
    formatted = re.sub(r" ?\n ?", "\n", formatted)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    return formatted or "응답을 생성했지만 표시할 내용이 없습니다."


def _truncate_kakao_text(text: str, limit: int) -> str:
    formatted = _format_kakao_display_text(text)
    if len(formatted) <= limit:
        return formatted
    return formatted[: limit - 3].rstrip() + "..."


def _kakao_suggestion_key(intent: str | None) -> str:
    if not intent:
        return "general"
    if intent.startswith("calendar"):
        return "calendar"
    if intent == "gmail_summary":
        return "gmail_summary"
    if intent.startswith("gmail"):
        return "gmail_action"
    if intent.startswith("macos_note"):
        return "notes"
    return "general"


def _build_kakao_suggestions(
    source_message: str | None,
    route: str,
    approval_ticket_id: str | None,
    action_type: str | None,
) -> tuple[list[KakaoButton] | None, list[KakaoQuickReply] | None]:
    intent = action_type or (classify_message_intent(source_message) if source_message else None)
    suggestion_items = KAKAO_SUGGESTION_PRESETS[_kakao_suggestion_key(intent)]

    if route == "approval_required" and approval_ticket_id:
        approval_items = [
            ("승인", f"승인 {approval_ticket_id}"),
            ("거절", f"거절 {approval_ticket_id}"),
        ]
        suggestion_items = approval_items + suggestion_items[:1]

    buttons = [
        KakaoButton(action="message", label=label, messageText=message_text)
        for label, message_text in suggestion_items[:3]
    ]
    quick_replies = [
        KakaoQuickReply(label=label, action="message", messageText=message_text)
        for label, message_text in suggestion_items[:3]
    ]
    return buttons or None, quick_replies or None


def _build_kakao_thumbnail() -> KakaoThumbnail:
    return KakaoThumbnail(
        imageUrl=KAKAO_BASIC_CARD_THUMBNAIL_URL,
        altText=KAKAO_BASIC_CARD_THUMBNAIL_ALT,
    )


def build_kakao_response(
    reply: str,
    session_id: str,
    route: str,
    approval_ticket_id: str | None = None,
    source_message: str | None = None,
    action_type: str | None = None,
) -> KakaoWebhookResponse:
    route_label = {
        "n8n": "자동화 응답",
        "n8n_fallback": "자동화 fallback 응답",
        "local_llm": "로컬 LLM 응답",
        "fallback": "fallback 응답",
        "approval_required": "승인 필요",
        "validation_error": "입력 확인 필요",
    }.get(route, "응답")
    card_detail = _truncate_kakao_text(reply, KAKAO_BASIC_CARD_DESCRIPTION_LIMIT)
    simple_detail = _truncate_kakao_text(reply, KAKAO_SIMPLE_TEXT_LIMIT)
    buttons, quick_replies = _build_kakao_suggestions(source_message, route, approval_ticket_id, action_type)
    thumbnail = _build_kakao_thumbnail()

    if route == "approval_required" and approval_ticket_id:
        outputs = [
            KakaoBasicCardOutput(
                basicCard=KakaoBasicCard(
                    title=route_label,
                    description=card_detail,
                    thumbnail=thumbnail,
                    buttons=buttons,
                )
            )
        ]
    elif route in {"n8n", "n8n_fallback"}:
        outputs = [
            KakaoBasicCardOutput(
                basicCard=KakaoBasicCard(
                    title=route_label,
                    description=card_detail,
                    thumbnail=thumbnail,
                    buttons=buttons,
                )
            )
        ]
    else:
        outputs = [
            KakaoSimpleTextOutput(
                simpleText=KakaoSimpleText(text=simple_detail)
            )
        ]

    return KakaoWebhookResponse(
        data={
            "session_id": session_id,
            "route": route,
            **({"approval_ticket_id": approval_ticket_id} if approval_ticket_id else {}),
        },
        template=KakaoTemplate(
            outputs=outputs,
            quickReplies=quick_replies,
        ),
    )


def build_kakao_pending_response(session_id: str, source_message: str | None = None) -> KakaoWebhookResponse:
    return KakaoWebhookResponse(
        useCallback=True,
        data={
            "text": KAKAO_CALLBACK_PENDING_MESSAGE,
            "session_id": session_id,
            "route": "callback_pending",
        },
    )


def _preview_kakao_text(text: str | None, limit: int = 80) -> str:
    if not text:
        return ""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _callback_host(callback_url: str | None) -> str | None:
    if not callback_url:
        return None
    try:
        return httpx.URL(callback_url).host
    except Exception:
        return None


def _summarize_kakao_response(response: KakaoWebhookResponse) -> dict[str, object]:
    outputs: list[str] = []
    if response.template is not None:
        for output in response.template.outputs:
            if isinstance(output, KakaoBasicCardOutput):
                outputs.append("basicCard")
            elif isinstance(output, KakaoSimpleTextOutput):
                outputs.append("simpleText")
            else:
                outputs.append(type(output).__name__)

    quick_reply_labels = [reply.label for reply in (response.template.quick_replies or [])] if response.template else []
    return {
        "use_callback": response.use_callback,
        "route": (response.data or {}).get("route"),
        "session_id": (response.data or {}).get("session_id"),
        "approval_ticket_id": (response.data or {}).get("approval_ticket_id"),
        "outputs": outputs,
        "quick_replies": quick_reply_labels,
        "has_template": response.template is not None,
        "data_keys": sorted((response.data or {}).keys()),
    }


def _log_kakao_response_summary(context: str, response: KakaoWebhookResponse) -> None:
    summary = _summarize_kakao_response(response)
    logger.info(
        "%s use_callback=%s route=%s session_id=%s approval_ticket_id=%s has_template=%s data_keys=%s outputs=%s quick_replies=%s",
        context,
        summary["use_callback"],
        summary["route"],
        summary["session_id"],
        summary["approval_ticket_id"],
        summary["has_template"],
        summary["data_keys"],
        summary["outputs"],
        summary["quick_replies"],
    )


def _resolve_kakao_session(
    db: Session,
    session_id: str | None,
    user_id: str | None,
    utterance: str,
) -> AssistantSession:
    if session_id:
        session = get_session_by_id(db, session_id)
        if session is not None:
            return update_session_message(db, session, utterance)
    return create_session(db, channel="kakao", user_id=user_id, message=utterance)


def _session_history_context(db: Session, session_id: str, limit: int = 8) -> list[dict[str, str]]:
    history = list_session_messages(db, session_id, limit=limit)
    return [
        {
            "role": item.role,
            "text": item.message_text or "",
            "route": item.route or "",
        }
        for item in history
    ]


def _build_structured_payload(
    message: str,
    channel: str,
    history: list[dict[str, str]] | None = None,
) -> StructuredExtraction:
    return extract_structured_request(message, channel, history)


def _record_user_message(
    db: Session,
    session: AssistantSession,
    channel: str,
    message: str,
    structured: StructuredExtraction | None = None,
) -> dict[str, object]:
    structured_payload = structured.model_dump(by_alias=True, exclude_none=True) if structured is not None else None
    create_session_message(
        db,
        session_id=session.id,
        role="user",
        channel=channel,
        message_text=message,
        structured_data=structured_payload,
    )
    if structured is not None:
        upsert_session_state(
            db,
            session_id=session.id,
            last_intent=structured.intent,
            last_extraction=structured_payload,
            state_data={"last_user_message": message},
        )
    else:
        upsert_session_state(
            db,
            session_id=session.id,
            state_data={"last_user_message": message},
        )
    return structured_payload or {}


def _record_assistant_message(
    db: Session,
    session_id: str,
    channel: str,
    reply: str,
    route: str,
    action_type: str | None = None,
    approval_ticket_id: str | None = None,
) -> None:
    message_meta: dict[str, object] = {}
    if action_type:
        message_meta["action_type"] = action_type
    if approval_ticket_id:
        message_meta["approval_ticket_id"] = approval_ticket_id

    create_session_message(
        db,
        session_id=session_id,
        role="assistant",
        channel=channel,
        message_text=reply,
        route=route,
        message_meta=message_meta or None,
    )
    upsert_session_state(
        db,
        session_id=session_id,
        last_route=route,
        pending_action=action_type if route == "approval_required" else None,
        pending_ticket_id=approval_ticket_id if route == "approval_required" else None,
        state_data={"last_assistant_reply": reply},
    )


def _process_kakao_message(
    db: Session,
    utterance: str,
    user_id: str | None,
    session_id: str | None = None,
) -> tuple[str, str, str, str | None, str | None]:
    approval_command = _match_approval_command(utterance)
    if approval_command is not None:
        return _handle_approval_command(approval_command, user_id, db)

    session = _resolve_kakao_session(db, session_id, user_id, utterance)
    structured = _build_structured_payload(utterance, "kakao", _session_history_context(db, session.id))
    _record_user_message(db, session, "kakao", utterance, structured)
    result = process_message(
        utterance,
        "kakao",
        session.id,
        user_id,
        structured_extraction=structured,
    )
    approval_ticket_id = None
    action_type = str(result["action_type"]) if result["action_type"] else None
    if result["route"] == "approval_required" and result["action_type"]:
        ticket = create_approval_ticket(db, session_id=session.id, action_type=action_type)
        create_task_run(
            db,
            session_id=session.id,
            task_type=action_type,
            detail=utterance,
            status="pending_approval",
        )
        approval_ticket_id = ticket.id
        reply = f"{result['reply']} ticket={ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=utterance)
        reply = str(result["reply"])

    _record_assistant_message(db, session.id, "kakao", reply, str(result["route"]), action_type, approval_ticket_id)

    return session.id, reply, str(result["route"]), approval_ticket_id, action_type


def _resolve_kakao_callback_session_id(db: Session, utterance: str, user_id: str | None) -> str:
    approval_command = _match_approval_command(utterance)
    if approval_command is not None:
        ticket = get_approval_ticket(db, approval_command[1])
        if ticket is not None and ticket.session_id:
            return ticket.session_id
        return "unknown"
    session = _resolve_kakao_session(db, None, user_id, utterance)
    return session.id


def _post_kakao_callback(callback_url: str, response: KakaoWebhookResponse) -> None:
    payload = response.model_dump(by_alias=True, exclude_none=True)
    with httpx.Client(timeout=10.0) as client:
        callback_response = client.post(callback_url, json=payload)
        callback_response.raise_for_status()
    logger.info(
        "Delivered Kakao callback response host=%s status_code=%s route=%s session_id=%s",
        _callback_host(callback_url),
        callback_response.status_code,
        payload.get("data", {}).get("route"),
        payload.get("data", {}).get("session_id"),
    )


def _process_kakao_callback(
    callback_url: str,
    utterance: str,
    user_id: str | None,
    session_id: str,
) -> None:
    db = SessionLocal()
    logger.info(
        "Starting Kakao callback job session_id=%s callback_host=%s utterance=%r user_id=%s",
        session_id,
        _callback_host(callback_url),
        _preview_kakao_text(utterance),
        user_id,
    )
    try:
        callback_session_id, reply, route, approval_ticket_id, action_type = _process_kakao_message(
            db,
            utterance,
            user_id,
            session_id,
        )
        logger.info(
            "Prepared Kakao callback response session_id=%s route=%s action_type=%s approval_ticket_id=%s",
            callback_session_id,
            route,
            action_type,
            approval_ticket_id,
        )
        response = build_kakao_response(
            reply,
            callback_session_id,
            route,
            approval_ticket_id,
            utterance,
            action_type,
        )
        _log_kakao_response_summary("Kakao callback response", response)
    except Exception:
        logger.exception("Failed to process Kakao callback message")
        response = build_kakao_response(
            KAKAO_CALLBACK_FAILURE_MESSAGE,
            session_id,
            "fallback",
            source_message=utterance,
        )
        _log_kakao_response_summary("Kakao callback fallback response", response)
    finally:
        db.close()

    try:
        _post_kakao_callback(callback_url, response)
    except Exception:
        logger.exception("Failed to deliver Kakao callback response")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    warm_local_llm()


@app.get("/api/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    database_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"

    return HealthResponse(
        status="ok",
        environment=settings.app_env,
        local_llm_provider=settings.local_llm.provider,
        local_llm_base_url=settings.local_llm.base_url,
        database_status=database_status,
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    approval_command = _match_approval_command(payload.message)
    if approval_command is not None:
        session_id, reply, route, approval_ticket_id, _ = _handle_approval_command(approval_command, None, db)
        return ChatResponse(
            reply=reply,
            route=route,
            local_llm_provider=settings.local_llm.provider,
            model=settings.local_llm.model,
            session_id=session_id,
            approval_ticket_id=approval_ticket_id,
        )

    session = get_session_by_id(db, payload.session_id) if payload.session_id else None
    if session is None:
        session = create_session(db, channel=payload.channel, user_id=None, message=payload.message)
    else:
        session = update_session_message(db, session, payload.message)

    structured = _build_structured_payload(payload.message, payload.channel, _session_history_context(db, session.id))
    _record_user_message(db, session, payload.channel, payload.message, structured)

    result = process_message(payload.message, payload.channel, session.id, structured_extraction=structured)
    approval_ticket_id = None
    if result["route"] == "approval_required" and result["action_type"]:
        ticket = create_approval_ticket(db, session_id=session.id, action_type=str(result["action_type"]))
        create_task_run(
            db,
            session_id=session.id,
            task_type=str(result["action_type"]),
            detail=payload.message,
            status="pending_approval",
        )
        approval_ticket_id = ticket.id
        reply = f"{result['reply']} ticket={ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=payload.message)
        reply = str(result["reply"])
    _record_assistant_message(
        db,
        session.id,
        payload.channel,
        reply,
        str(result["route"]),
        str(result["action_type"]) if result["action_type"] else None,
        approval_ticket_id,
    )
    return ChatResponse(
        reply=reply,
        route=str(result["route"]),
        local_llm_provider=settings.local_llm.provider,
        model=settings.local_llm.model,
        session_id=session.id,
        approval_ticket_id=approval_ticket_id,
    )


@app.post("/api/browser/read", response_model=BrowserReadResponse)
async def browser_read(payload: BrowserReadRequest, db: Session = Depends(get_db)) -> BrowserReadResponse:
    session = get_session_by_id(db, payload.session_id) if payload.session_id else None
    if session is None:
        session = create_session(db, channel=payload.channel, user_id=None, message=payload.url)
    else:
        session = update_session_message(db, session, payload.url)

    task = create_task_run(
        db,
        session_id=session.id,
        task_type="browser_readonly",
        detail=payload.url,
        status="running",
    )
    request_body = {
        "url": payload.url,
        "waitSelector": payload.wait_selector,
        "timeoutMs": payload.timeout_ms,
        "maxChars": payload.max_chars,
    }

    try:
        async with httpx.AsyncClient(timeout=(payload.timeout_ms / 1000) + 10.0) as client:
            response = await client.post(
                f"{settings.browser_runner_base_url.rstrip('/')}/browse/read",
                json=request_body,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        update_task_run_status(db, task, status="failed", detail=f"{payload.url}\n{exc.response.text}")
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        update_task_run_status(db, task, status="failed", detail=f"{payload.url}\n{exc}")
        raise HTTPException(status_code=502, detail=f"browser runner unavailable: {exc}") from exc

    data = response.json()
    update_task_run_status(db, task, status="completed", detail=data.get("title") or payload.url)
    return BrowserReadResponse(
        session_id=session.id,
        taskId=task.id,
        route="browser_readonly",
        url=str(data["url"]),
        finalUrl=str(data["finalUrl"]),
        title=str(data["title"]),
        description=str(data["description"]) if data.get("description") else None,
        headings=[str(item) for item in data.get("headings") or []],
        contentExcerpt=str(data["contentExcerpt"]),
        fetchedAt=data["fetchedAt"],
    )


@app.post("/api/slack/events")
@app.post("/api/slack/events/")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
) -> dict[str, str]:
    raw_body = await request.body()
    if settings.slack_signing_secret and not _is_valid_slack_signature(
        raw_body,
        x_slack_request_timestamp,
        x_slack_signature,
    ):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    payload = json.loads(raw_body.decode("utf-8") or "{}")
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        if not isinstance(challenge, str):
            raise HTTPException(status_code=400, detail="missing slack challenge")
        return {"challenge": challenge}

    if payload.get("type") != "event_callback":
        return {"status": "ignored"}

    event = payload.get("event") or {}
    if not _should_process_slack_event(event):
        return {"status": "ignored"}

    text = _normalize_slack_message_text(str(event.get("text") or ""))
    user_id = str(event.get("user") or "") or None
    channel_id = str(event.get("channel") or "") or None
    thread_ts = _slack_thread_ts(event)
    session_id = _resolve_slack_event_session_id(db, text, user_id)
    logger.info(
        "Received Slack event user_id=%s channel_id=%s thread_ts=%s session_id=%s message=%r",
        user_id,
        channel_id,
        thread_ts,
        session_id,
        _preview_kakao_text(text),
    )
    background_tasks.add_task(
        _process_slack_event_async,
        channel_id,
        thread_ts,
        text,
        user_id,
        session_id,
    )

    return {
        "status": "accepted",
        "session_id": session_id,
        "delivery": "scheduled",
    }


@app.post("/api/slack/interactions")
@app.post("/api/slack/interactions/")
async def slack_interactions(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
) -> dict[str, str]:
    raw_body = await request.body()
    if settings.slack_signing_secret and not _is_valid_slack_signature(
        raw_body,
        x_slack_request_timestamp,
        x_slack_signature,
    ):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    form_data = parse_qs(raw_body.decode("utf-8") or "")
    payload_raw = form_data.get("payload", ["{}"])[0]
    payload = json.loads(payload_raw)
    if payload.get("type") != "block_actions":
        return {"status": "ignored"}

    actions = payload.get("actions") or []
    if not actions:
        return {"status": "ignored"}

    action_payload = actions[0]
    action_id = str(action_payload.get("action_id") or "")
    ticket_id = str(action_payload.get("value") or "")
    action = "approve" if action_id == "approve_ticket" else "reject" if action_id == "reject_ticket" else ""
    if not action or not ticket_id:
        return {"status": "ignored"}

    channel_id = str((payload.get("channel") or {}).get("id") or "")
    actor_id = str((payload.get("user") or {}).get("id") or "") or None
    container = payload.get("container") or {}
    message = payload.get("message") or {}
    thread_ts = str(container.get("thread_ts") or message.get("thread_ts") or message.get("ts") or "") or None
    logger.info(
        "Received Slack interaction action=%s ticket_id=%s actor_id=%s channel_id=%s thread_ts=%s",
        action,
        ticket_id,
        actor_id,
        channel_id,
        thread_ts,
    )
    background_tasks.add_task(
        _process_slack_interaction_async,
        action,
        ticket_id,
        actor_id,
        channel_id,
        thread_ts,
    )
    return {
        "text": "승인 요청을 처리 중입니다. 잠시 후 결과를 이어서 알려드리겠습니다.",
        "response_type": "ephemeral",
    }


@app.post("/api/kakao/webhook", response_model=KakaoWebhookResponse, response_model_exclude_none=True)
def kakao_webhook(
    payload: KakaoWebhookUtterance,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> KakaoWebhookResponse:
    utterance = payload.resolved_utterance()
    user_id = payload.resolved_user_id()
    callback_url = payload.resolved_callback_url()
    if not utterance:
        raise HTTPException(status_code=400, detail="kakao utterance not found")

    logger.info(
        "Received Kakao webhook user_id=%s has_callback=%s callback_host=%s utterance=%r",
        user_id,
        bool(callback_url),
        _callback_host(callback_url),
        _preview_kakao_text(utterance),
    )

    if callback_url:
        session_id = _resolve_kakao_callback_session_id(db, utterance, user_id)
        logger.info(
            "Kakao webhook using callback path session_id=%s utterance=%r",
            session_id,
            _preview_kakao_text(utterance),
        )
        pending_response = build_kakao_pending_response(session_id, utterance)
        _log_kakao_response_summary("Kakao pending response", pending_response)
        background_tasks.add_task(
            _process_kakao_callback,
            callback_url,
            utterance,
            user_id,
            session_id,
        )
        return pending_response

    session_id, reply, route, approval_ticket_id, action_type = _process_kakao_message(
        db,
        utterance,
        user_id,
    )
    response = build_kakao_response(reply, session_id, route, approval_ticket_id, utterance, action_type)
    logger.info(
        "Kakao webhook completed sync path session_id=%s route=%s action_type=%s approval_ticket_id=%s utterance=%r",
        session_id,
        route,
        action_type,
        approval_ticket_id,
        _preview_kakao_text(utterance),
    )
    if route == "approval_required":
        _log_kakao_response_summary("Kakao approval sync response", response)
    return response


@app.post("/api/actions/approve", response_model=ApprovalTicketResponse)
def approve_action(payload: ApprovalActionRequest, db: Session = Depends(get_db)) -> ApprovalTicketResponse:
    ticket = get_approval_ticket(db, payload.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="approval ticket not found")
    ticket = update_approval_ticket_status(db, ticket, status="approved", actor_id=payload.actor_id)
    execution_reply, route = _execute_pending_ticket(ticket, db)
    return ApprovalTicketResponse(
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        action_type=ticket.action_type,
        status=ticket.status,
        actor_id=ticket.actor_id,
        execution_reply=execution_reply,
        route=route,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@app.post("/api/actions/reject", response_model=ApprovalTicketResponse)
def reject_action(payload: ApprovalActionRequest, db: Session = Depends(get_db)) -> ApprovalTicketResponse:
    ticket = get_approval_ticket(db, payload.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="approval ticket not found")
    ticket = update_approval_ticket_status(db, ticket, status="rejected", actor_id=payload.actor_id)
    pending_task = get_latest_task_run(db, ticket.session_id, task_type=ticket.action_type, status="pending_approval")
    if pending_task is not None:
        update_task_run_status(db, pending_task, status="rejected")
    return ApprovalTicketResponse(
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        action_type=ticket.action_type,
        status=ticket.status,
        actor_id=ticket.actor_id,
        execution_reply="승인 요청을 거절했습니다.",
        route="rejected",
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)) -> SessionResponse:
    session = get_session_by_id(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionResponse(
        session_id=session.id,
        user_id=session.user_id,
        channel=session.channel,
        status=session.status,
        summary=session.summary,
        last_message=session.last_message,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@app.get("/api/sessions/{session_id}/messages", response_model=list[SessionMessageResponse])
def get_session_messages(session_id: str, limit: int = 20, db: Session = Depends(get_db)) -> list[SessionMessageResponse]:
    session = get_session_by_id(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = list_session_messages(db, session_id, limit=max(1, min(limit, 100)))
    return [
        SessionMessageResponse(
            messageId=message.id,
            sessionId=message.session_id,
            role=message.role,
            channel=message.channel,
            messageText=message.message_text,
            route=message.route,
            structuredData=message.structured_data,
            messageMeta=message.message_meta,
            createdAt=message.created_at,
        )
        for message in messages
    ]


@app.get("/api/sessions/{session_id}/state", response_model=SessionStateResponse)
def get_session_state_api(session_id: str, db: Session = Depends(get_db)) -> SessionStateResponse:
    session = get_session_by_id(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    state = get_session_state(db, session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session state not found")
    return SessionStateResponse(
        sessionId=state.session_id,
        lastIntent=state.last_intent,
        lastRoute=state.last_route,
        pendingAction=state.pending_action,
        pendingTicketId=state.pending_ticket_id,
        lastExtraction=state.last_extraction,
        lastCandidates=state.last_candidates,
        stateData=state.state_data,
        createdAt=state.created_at,
        updatedAt=state.updated_at,
    )


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskResponse:
    task = get_task_run(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskResponse(
        task_id=task.id,
        session_id=task.session_id,
        status=task.status,
        task_type=task.task_type,
        detail=task.detail,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@app.post("/api/actions/request-approval", response_model=ApprovalTicketResponse)
def request_approval(session_id: str | None = None, db: Session = Depends(get_db)) -> ApprovalTicketResponse:
    ticket = create_approval_ticket(db, session_id=session_id, action_type="manual_approval")
    return ApprovalTicketResponse(
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        action_type=ticket.action_type,
        status=ticket.status,
        actor_id=ticket.actor_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _match_approval_command(message: str) -> tuple[str, str] | None:
    approve = APPROVE_PATTERN.match(message.strip())
    if approve:
        return "approve", approve.group(2)
    reject = REJECT_PATTERN.match(message.strip())
    if reject:
        return "reject", reject.group(2)
    return None


def _handle_approval_command(
    command: tuple[str, str],
    actor_id: str | None,
    db: Session,
) -> tuple[str, str, str, str | None, str | None]:
    action, ticket_id = command
    command_text = f"{'승인' if action == 'approve' else '거절'} {ticket_id}"
    ticket = get_approval_ticket(db, ticket_id)
    if ticket is None:
        return "unknown", "승인 티켓을 찾지 못했습니다.", "not_found", None, None
    if ticket.session_id:
        session = get_session_by_id(db, ticket.session_id)
        if session is not None:
            _record_user_message(db, session, session.channel, command_text)
    if ticket.status != "pending":
        status_label = "승인됨" if ticket.status == "approved" else "거절됨" if ticket.status == "rejected" else ticket.status
        reply = f"이 승인 요청은 이미 {status_label} 상태입니다."
        if ticket.session_id:
            _record_assistant_message(db, ticket.session_id, "system", reply, f"already_{ticket.status}", ticket.action_type, ticket.id)
        return (
            ticket.session_id or "unknown",
            reply,
            f"already_{ticket.status}",
            ticket.id,
            ticket.action_type,
        )
    if action == "reject":
        ticket = update_approval_ticket_status(db, ticket, status="rejected", actor_id=actor_id)
        pending_task = get_latest_task_run(db, ticket.session_id, task_type=ticket.action_type, status="pending_approval")
        if pending_task is not None:
            update_task_run_status(db, pending_task, status="rejected")
        reply = "승인 요청을 거절했습니다."
        if ticket.session_id:
            _record_assistant_message(db, ticket.session_id, "system", reply, "rejected", ticket.action_type, ticket.id)
        return ticket.session_id or "unknown", reply, "rejected", ticket.id, ticket.action_type

    ticket = update_approval_ticket_status(db, ticket, status="approved", actor_id=actor_id)
    execution_reply, route = _execute_pending_ticket(ticket, db)
    if ticket.session_id:
        _record_assistant_message(
            db,
            ticket.session_id,
            "system",
            execution_reply or "승인 처리했습니다.",
            route or "approved",
            ticket.action_type,
            ticket.id,
        )
    return ticket.session_id or "unknown", execution_reply or "승인 처리했습니다.", route or "approved", ticket.id, ticket.action_type


def _execute_pending_ticket(ticket: ApprovalTicket, db: Session) -> tuple[str | None, str | None]:
    if ticket.session_id is None:
        return None, None
    pending_task = get_latest_task_run(db, ticket.session_id, task_type=ticket.action_type, status="pending_approval")
    session = get_session_by_id(db, ticket.session_id)
    if pending_task is None or session is None or pending_task.detail is None:
        return "실행할 대기 작업을 찾지 못했습니다.", "missing_pending_task"
    result = process_message(
        pending_task.detail,
        session.channel,
        session.id,
        session.user_id,
        intent_override=ticket.action_type,
        approval_granted=True,
        structured_extraction=extract_structured_request(
            pending_task.detail,
            session.channel,
            _session_history_context(db, session.id),
        ),
    )
    update_task_run_status(db, pending_task, status="completed", detail=pending_task.detail)
    return str(result["reply"]), str(result["route"])


def _resolve_slack_session(
    db: Session,
    session_id: str | None,
    user_id: str | None,
    message: str,
) -> AssistantSession:
    if session_id:
        session = get_session_by_id(db, session_id)
        if session is not None:
            return update_session_message(db, session, message)
    return create_session(db, channel="slack", user_id=user_id, message=message)


def _process_slack_message(
    db: Session,
    message: str,
    user_id: str | None,
    session_id: str | None = None,
) -> tuple[str, str, str, str | None, str | None]:
    approval_command = _match_approval_command(message)
    if approval_command is not None:
        return _handle_approval_command(approval_command, user_id, db)

    session = _resolve_slack_session(db, session_id, user_id, message)
    structured = _build_structured_payload(message, "slack", _session_history_context(db, session.id))
    _record_user_message(db, session, "slack", message, structured)
    result = process_message(message, "slack", session.id, user_id, structured_extraction=structured)
    approval_ticket_id = None
    action_type = str(result["action_type"]) if result["action_type"] else None
    if result["route"] == "approval_required" and result["action_type"]:
        ticket = create_approval_ticket(db, session_id=session.id, action_type=action_type)
        create_task_run(
            db,
            session_id=session.id,
            task_type=action_type,
            detail=message,
            status="pending_approval",
        )
        approval_ticket_id = ticket.id
        reply = f"{result['reply']} ticket={ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=message)
        reply = str(result["reply"])

    _record_assistant_message(db, session.id, "slack", reply, str(result["route"]), action_type, approval_ticket_id)

    return session.id, reply, str(result["route"]), approval_ticket_id, action_type


def _resolve_slack_event_session_id(db: Session, message: str, user_id: str | None) -> str:
    approval_command = _match_approval_command(message)
    if approval_command is not None:
        ticket = get_approval_ticket(db, approval_command[1])
        if ticket is not None and ticket.session_id:
            return ticket.session_id
        return "unknown"
    session = _resolve_slack_session(db, None, user_id, message)
    return session.id


def _slack_thread_ts(event: dict[str, object]) -> str | None:
    return str(event.get("thread_ts") or event.get("ts") or "") or None


def _build_slack_approval_blocks(reply: str, approval_ticket_id: str) -> list[dict[str, object]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": reply,
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "승인"},
                    "style": "primary",
                    "action_id": "approve_ticket",
                    "value": approval_ticket_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "거절"},
                    "style": "danger",
                    "action_id": "reject_ticket",
                    "value": approval_ticket_id,
                },
            ],
        },
    ]


def _post_slack_response(
    channel_id: str,
    reply: str,
    route: str,
    approval_ticket_id: str | None = None,
    thread_ts: str | None = None,
) -> str:
    blocks = None
    if route == "approval_required" and approval_ticket_id:
        blocks = _build_slack_approval_blocks(reply, approval_ticket_id)
    return _post_slack_message(channel_id, reply, thread_ts=thread_ts, blocks=blocks)


def _process_slack_event_async(
    channel_id: str,
    thread_ts: str | None,
    message: str,
    user_id: str | None,
    session_id: str,
) -> None:
    db = SessionLocal()
    logger.info(
        "Starting Slack background job session_id=%s channel_id=%s user_id=%s thread_ts=%s message=%r",
        session_id,
        channel_id,
        user_id,
        thread_ts,
        _preview_kakao_text(message),
    )
    try:
        if settings.slack_bot_token:
            pending_delivery = _post_slack_message(channel_id, SLACK_PENDING_MESSAGE, thread_ts=thread_ts)
            logger.info(
                "Sent Slack pending response session_id=%s delivery=%s thread_ts=%s",
                session_id,
                pending_delivery,
                thread_ts,
            )

        callback_session_id, reply, route, approval_ticket_id, _ = _process_slack_message(
            db,
            message,
            user_id,
            session_id,
        )
        delivery = "not_configured"
        if settings.slack_bot_token:
            delivery = _post_slack_response(
                channel_id,
                reply,
                route,
                approval_ticket_id=approval_ticket_id,
                thread_ts=thread_ts,
            )
        logger.info(
            "Completed Slack background job session_id=%s route=%s approval_ticket_id=%s delivery=%s",
            callback_session_id,
            route,
            approval_ticket_id,
            delivery,
        )
    except Exception:
        logger.exception("Failed to process Slack background message")
        if settings.slack_bot_token:
            failure_delivery = _post_slack_message(channel_id, SLACK_FAILURE_MESSAGE, thread_ts=thread_ts)
            logger.info(
                "Sent Slack failure response session_id=%s delivery=%s",
                session_id,
                failure_delivery,
            )
    finally:
        db.close()


def _process_slack_interaction_async(
    action: str,
    ticket_id: str,
    actor_id: str | None,
    channel_id: str,
    thread_ts: str | None,
) -> None:
    db = SessionLocal()
    logger.info(
        "Starting Slack interaction action=%s ticket_id=%s actor_id=%s channel_id=%s thread_ts=%s",
        action,
        ticket_id,
        actor_id,
        channel_id,
        thread_ts,
    )
    try:
        session_id, reply, route, approval_ticket_id, _ = _handle_approval_command((action, ticket_id), actor_id, db)
        delivery = "not_configured"
        if settings.slack_bot_token:
            delivery = _post_slack_response(
                channel_id,
                reply,
                route,
                approval_ticket_id=approval_ticket_id if route == "approval_required" else None,
                thread_ts=thread_ts,
            )
        logger.info(
            "Completed Slack interaction session_id=%s route=%s ticket_id=%s delivery=%s",
            session_id,
            route,
            approval_ticket_id,
            delivery,
        )
    except Exception:
        logger.exception("Failed to process Slack interaction")
        if settings.slack_bot_token:
            _post_slack_message(channel_id, SLACK_FAILURE_MESSAGE, thread_ts=thread_ts)
    finally:
        db.close()


def _is_valid_slack_signature(
    raw_body: bytes,
    request_timestamp: str | None,
    request_signature: str | None,
) -> bool:
    if not request_timestamp or not request_signature:
        return False
    try:
        timestamp = int(request_timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp) > 60 * 5:
        return False
    basestring = f"v0:{request_timestamp}:{raw_body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, request_signature)


def _normalize_slack_channel_name(name: str) -> str:
    return name.strip().lstrip("#").lower()


def _resolve_slack_channel_name(channel_id: str) -> str | None:
    cached = SLACK_CHANNEL_NAME_CACHE.get(channel_id)
    if cached:
        return cached
    if not settings.slack_bot_token or not channel_id:
        return None
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://slack.com/api/conversations.info",
                headers={
                    "Authorization": f"Bearer {settings.slack_bot_token}",
                },
                params={"channel": channel_id},
            )
            response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            return None
        channel_name = _normalize_slack_channel_name(str((payload.get("channel") or {}).get("name") or ""))
        if channel_name:
            SLACK_CHANNEL_NAME_CACHE[channel_id] = channel_name
        return channel_name or None
    except Exception:
        logger.exception("Failed to resolve Slack channel name channel_id=%s", channel_id)
        return None


def _is_slack_auto_response_channel(channel_id: str) -> bool:
    allowed_channels = settings.slack_auto_response_channels
    if not allowed_channels or not channel_id:
        return False
    if _normalize_slack_channel_name(channel_id) in allowed_channels:
        return True
    channel_name = _resolve_slack_channel_name(channel_id)
    return bool(channel_name and channel_name in allowed_channels)


def _should_process_slack_event(event: dict[str, object]) -> bool:
    event_type = str(event.get("type") or "")
    subtype = str(event.get("subtype") or "")
    if event_type not in {"message", "app_mention"}:
        return False
    if subtype:
        return False
    if event.get("bot_id") or not event.get("user"):
        return False
    if not event.get("channel") or not event.get("text"):
        return False
    channel_id = str(event.get("channel") or "")
    channel_type = str(event.get("channel_type") or "")
    return event_type == "app_mention" or channel_type == "im" or _is_slack_auto_response_channel(channel_id)


def _normalize_slack_message_text(message: str) -> str:
    return re.sub(r"<@[A-Z0-9]+>", "", message).strip()


def _post_slack_message(
    channel_id: str,
    text: str,
    thread_ts: str | None = None,
    blocks: list[dict[str, object]] | None = None,
) -> str:
    try:
        request_payload: dict[str, object] = {"channel": channel_id, "text": text}
        if thread_ts:
            request_payload["thread_ts"] = thread_ts
        if blocks:
            request_payload["blocks"] = blocks
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {settings.slack_bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=request_payload,
            )
            response.raise_for_status()
        response_payload = response.json()
        return "sent" if response_payload.get("ok") else f"slack_api_error:{response_payload.get('error', 'unknown')}"
    except Exception:
        return "delivery_failed"
