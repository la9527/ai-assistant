import hashlib
import hmac
import json
import re
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import Depends
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request

import httpx

from app.automation import process_message
from app.config import settings
from app.db import Base
from app.db import engine
from app.db import get_db
from app.models import ApprovalTicket
from app.models import AssistantSession
from app.models import TaskRun
from app.repositories import create_approval_ticket
from app.repositories import create_session
from app.repositories import create_task_run
from app.repositories import get_approval_ticket
from app.repositories import get_latest_task_run
from app.repositories import get_session_by_id
from app.repositories import get_task_run
from app.repositories import update_task_run_status
from app.repositories import update_approval_ticket_status
from app.repositories import update_session_message
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
from app.schemas import KakaoWebhookResponse
from app.schemas import KakaoWebhookUtterance
from app.schemas import SessionResponse
from app.schemas import TaskResponse


app = FastAPI(title="AI Assistant API", version="0.1.0")

APPROVE_PATTERN = re.compile(r"^(승인|approve)\s+([a-zA-Z0-9-]+)$", re.IGNORECASE)
REJECT_PATTERN = re.compile(r"^(거절|reject)\s+([a-zA-Z0-9-]+)$", re.IGNORECASE)
KAKAO_BASIC_CARD_DESCRIPTION_LIMIT = 230
KAKAO_SIMPLE_TEXT_LIMIT = 1000

DEFAULT_KAKAO_QUICK_REPLIES = [
    KakaoQuickReply(label="일정 요약", action="message", messageText="오늘 일정 요약해줘"),
    KakaoQuickReply(label="메일 요약", action="message", messageText="최근 메일 요약해줘"),
    KakaoQuickReply(
        label="일정 삭제",
        action="message",
        messageText="내일 오후 3시 회의 일정 삭제해줘",
    ),
    KakaoQuickReply(
        label="메일 초안",
        action="message",
        messageText="test@example.com로 제목 안부, 내용 안녕하세요 메일 초안 작성해줘",
    ),
    KakaoQuickReply(
        label="첨부 초안",
        action="message",
        messageText="test@example.com로 제목 첨부 안내, 내용 첨부 확인 부탁드립니다 첨부 https://raw.githubusercontent.com/github/gitignore/main/README.md 메일 초안 작성해줘",
    ),
    KakaoQuickReply(
        label="메일 회신",
        action="message",
        messageText="제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘",
    ),
    KakaoQuickReply(
        label="첨부 회신",
        action="message",
        messageText="제목 AI Assistant Gmail 발송 테스트 내용 첨부 확인 부탁드립니다 첨부 https://raw.githubusercontent.com/github/gitignore/main/README.md 메일에 답장해줘",
    ),
]


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


def build_kakao_response(
    reply: str,
    session_id: str,
    route: str,
    approval_ticket_id: str | None = None,
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

    if route == "approval_required" and approval_ticket_id:
        outputs = [
            KakaoBasicCardOutput(
                basicCard=KakaoBasicCard(
                    title=route_label,
                    description=card_detail,
                    buttons=[
                        KakaoButton(action="message", label="승인", messageText=f"승인 {approval_ticket_id}"),
                        KakaoButton(action="message", label="거절", messageText=f"거절 {approval_ticket_id}"),
                    ],
                )
            )
        ]
        quick_replies = [
            KakaoQuickReply(label="승인", action="message", messageText=f"승인 {approval_ticket_id}"),
            KakaoQuickReply(label="거절", action="message", messageText=f"거절 {approval_ticket_id}"),
            DEFAULT_KAKAO_QUICK_REPLIES[4],
            DEFAULT_KAKAO_QUICK_REPLIES[6],
        ]
    elif route in {"n8n", "n8n_fallback"}:
        outputs = [
            KakaoBasicCardOutput(
                basicCard=KakaoBasicCard(
                    title=route_label,
                    description=card_detail,
                    buttons=[
                        KakaoButton(action="message", label="오늘 일정 다시 확인", messageText="오늘 일정 다시 요약해줘"),
                        KakaoButton(action="message", label="최근 메일 확인", messageText="최근 메일 요약해줘"),
                        KakaoButton(action="message", label="메일 초안 작성", messageText="test@example.com로 제목 안부, 내용 안녕하세요 메일 초안 작성해줘"),
                        KakaoButton(action="message", label="첨부 초안 작성", messageText="test@example.com로 제목 첨부 안내, 내용 첨부 확인 부탁드립니다 첨부 https://raw.githubusercontent.com/github/gitignore/main/README.md 메일 초안 작성해줘"),
                        KakaoButton(action="message", label="첨부 회신", messageText="제목 AI Assistant Gmail 발송 테스트 내용 첨부 확인 부탁드립니다 첨부 https://raw.githubusercontent.com/github/gitignore/main/README.md 메일에 답장해줘"),
                    ],
                )
            )
        ]
        quick_replies = DEFAULT_KAKAO_QUICK_REPLIES
    else:
        outputs = [
            KakaoSimpleTextOutput(
                simpleText=KakaoSimpleText(text=simple_detail)
            )
        ]
        quick_replies = DEFAULT_KAKAO_QUICK_REPLIES

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


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


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
        session_id, reply, route, approval_ticket_id = _handle_approval_command(approval_command, None, db)
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

    result = process_message(payload.message, payload.channel, session.id)
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

    approval_command = _match_approval_command(text)
    approval_ticket_id: str | None = None
    if approval_command is not None:
        session_id, reply, route, approval_ticket_id = _handle_approval_command(approval_command, user_id, db)
    else:
        session = create_session(db, channel="slack", user_id=user_id, message=text)
        result = process_message(text, "slack", session.id, user_id)
        session_id = session.id
        route = str(result["route"])
        if result["route"] == "approval_required" and result["action_type"]:
            ticket = create_approval_ticket(db, session_id=session.id, action_type=str(result["action_type"]))
            create_task_run(
                db,
                session_id=session.id,
                task_type=str(result["action_type"]),
                detail=text,
                status="pending_approval",
            )
            approval_ticket_id = ticket.id
            reply = f"{result['reply']} ticket={ticket.id}"
        else:
            create_task_run(db, session_id=session.id, task_type=route, detail=text)
            reply = str(result["reply"])

    delivery = "not_configured"
    if channel_id and settings.slack_bot_token:
        delivery = _post_slack_message(channel_id, reply)

    return {
        "status": "accepted",
        "route": route,
        "session_id": session_id,
        "delivery": delivery,
        **({"approval_ticket_id": approval_ticket_id} if approval_ticket_id else {}),
    }


@app.post("/api/kakao/webhook", response_model=KakaoWebhookResponse, response_model_exclude_none=True)
def kakao_webhook(payload: KakaoWebhookUtterance, db: Session = Depends(get_db)) -> KakaoWebhookResponse:
    utterance = payload.resolved_utterance()
    user_id = payload.resolved_user_id()
    if not utterance:
        raise HTTPException(status_code=400, detail="kakao utterance not found")

    approval_command = _match_approval_command(utterance)
    if approval_command is not None:
        session_id, reply, route, approval_ticket_id = _handle_approval_command(approval_command, user_id, db)
        return build_kakao_response(reply, session_id, route, approval_ticket_id)

    session = create_session(
        db,
        channel="kakao",
        user_id=user_id,
        message=utterance,
    )
    result = process_message(
        utterance,
        "kakao",
        session.id,
        user_id,
    )
    approval_ticket_id = None
    if result["route"] == "approval_required" and result["action_type"]:
        ticket = create_approval_ticket(db, session_id=session.id, action_type=str(result["action_type"]))
        create_task_run(
            db,
            session_id=session.id,
            task_type=str(result["action_type"]),
            detail=utterance,
            status="pending_approval",
        )
        approval_ticket_id = ticket.id
        reply = f"{result['reply']} ticket={ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=utterance)
        reply = str(result["reply"])
    return build_kakao_response(reply, session.id, str(result["route"]), approval_ticket_id)


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
) -> tuple[str, str, str, str | None]:
    action, ticket_id = command
    ticket = get_approval_ticket(db, ticket_id)
    if ticket is None:
        return "unknown", "승인 티켓을 찾지 못했습니다.", "not_found", None
    if action == "reject":
        ticket = update_approval_ticket_status(db, ticket, status="rejected", actor_id=actor_id)
        pending_task = get_latest_task_run(db, ticket.session_id, task_type=ticket.action_type, status="pending_approval")
        if pending_task is not None:
            update_task_run_status(db, pending_task, status="rejected")
        return ticket.session_id or "unknown", "승인 요청을 거절했습니다.", "rejected", ticket.id

    ticket = update_approval_ticket_status(db, ticket, status="approved", actor_id=actor_id)
    execution_reply, route = _execute_pending_ticket(ticket, db)
    return ticket.session_id or "unknown", execution_reply or "승인 처리했습니다.", route or "approved", ticket.id


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
    )
    update_task_run_status(db, pending_task, status="completed", detail=pending_task.detail)
    return str(result["reply"]), str(result["route"])


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
    channel_type = str(event.get("channel_type") or "")
    return event_type == "app_mention" or channel_type == "im"


def _normalize_slack_message_text(message: str) -> str:
    return re.sub(r"<@[A-Z0-9]+>", "", message).strip()


def _post_slack_message(channel_id: str, text: str) -> str:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {settings.slack_bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"channel": channel_id, "text": text},
            )
            response.raise_for_status()
        payload = response.json()
        return "sent" if payload.get("ok") else f"slack_api_error:{payload.get('error', 'unknown')}"
    except Exception:
        return "delivery_failed"
