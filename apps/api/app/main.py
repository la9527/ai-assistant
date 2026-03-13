import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException

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
    detail = f"{reply}\n\nsession={session_id}, route={route}"

    if route == "approval_required" and approval_ticket_id:
        outputs = [
            KakaoBasicCardOutput(
                basicCard=KakaoBasicCard(
                    title=route_label,
                    description=detail,
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
                    description=detail,
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
                simpleText=KakaoSimpleText(text=detail)
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


@app.post("/api/slack/events")
def slack_events() -> dict[str, str]:
    return {"status": "accepted"}


@app.post("/api/kakao/webhook", response_model=KakaoWebhookResponse)
def kakao_webhook(payload: KakaoWebhookUtterance, db: Session = Depends(get_db)) -> KakaoWebhookResponse:
    approval_command = _match_approval_command(payload.utterance)
    if approval_command is not None:
        session_id, reply, route, approval_ticket_id = _handle_approval_command(approval_command, payload.user.id if payload.user else None, db)
        return build_kakao_response(reply, session_id, route, approval_ticket_id)

    session = create_session(
        db,
        channel="kakao",
        user_id=payload.user.id if payload.user else None,
        message=payload.utterance,
    )
    result = process_message(
        payload.utterance,
        "kakao",
        session.id,
        payload.user.id if payload.user else None,
    )
    approval_ticket_id = None
    if result["route"] == "approval_required" and result["action_type"]:
        ticket = create_approval_ticket(db, session_id=session.id, action_type=str(result["action_type"]))
        create_task_run(
            db,
            session_id=session.id,
            task_type=str(result["action_type"]),
            detail=payload.utterance,
            status="pending_approval",
        )
        approval_ticket_id = ticket.id
        reply = f"{result['reply']} ticket={ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=payload.utterance)
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
