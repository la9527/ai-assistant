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
from app.repositories import get_session_by_id
from app.repositories import get_task_run
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


def build_kakao_response(reply: str, session_id: str, route: str) -> KakaoWebhookResponse:
    route_label = {
        "n8n": "자동화 응답",
        "n8n_fallback": "자동화 fallback 응답",
        "local_llm": "로컬 LLM 응답",
        "fallback": "fallback 응답",
    }.get(route, "응답")
    detail = f"{reply}\n\nsession={session_id}, route={route}"

    if route in {"n8n", "n8n_fallback"}:
        outputs = [
            KakaoBasicCardOutput(
                basicCard=KakaoBasicCard(
                    title=route_label,
                    description=detail,
                    buttons=[
                        KakaoButton(action="message", label="오늘 일정 다시 확인", messageText="오늘 일정 다시 요약해줘"),
                        KakaoButton(action="message", label="최근 메일 확인", messageText="최근 메일 요약해줘"),
                    ],
                )
            )
        ]
    else:
        outputs = [
            KakaoSimpleTextOutput(
                simpleText=KakaoSimpleText(text=detail)
            )
        ]

    return KakaoWebhookResponse(
        data={"session_id": session_id, "route": route},
        template=KakaoTemplate(
            outputs=outputs,
            quickReplies=[
                KakaoQuickReply(label="일정 요약", action="message", messageText="오늘 일정 요약해줘"),
                KakaoQuickReply(label="메일 요약", action="message", messageText="최근 메일 요약해줘"),
            ],
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
    session = get_session_by_id(db, payload.session_id) if payload.session_id else None
    if session is None:
        session = create_session(db, channel=payload.channel, user_id=None, message=payload.message)
    else:
        session = update_session_message(db, session, payload.message)

    reply, route = process_message(payload.message, payload.channel, session.id)
    create_task_run(db, session_id=session.id, task_type=route, detail=payload.message)
    return ChatResponse(
        reply=reply,
        route=route,
        local_llm_provider=settings.local_llm.provider,
        model=settings.local_llm.model,
        session_id=session.id,
    )


@app.post("/api/slack/events")
def slack_events() -> dict[str, str]:
    return {"status": "accepted"}


@app.post("/api/kakao/webhook", response_model=KakaoWebhookResponse)
def kakao_webhook(payload: KakaoWebhookUtterance, db: Session = Depends(get_db)) -> KakaoWebhookResponse:
    session = create_session(
        db,
        channel="kakao",
        user_id=payload.user.id if payload.user else None,
        message=payload.utterance,
    )
    reply, route = process_message(
        payload.utterance,
        "kakao",
        session.id,
        payload.user.id if payload.user else None,
    )
    create_task_run(db, session_id=session.id, task_type=route, detail=payload.utterance)
    return build_kakao_response(reply, session.id, route)


@app.post("/api/actions/approve", response_model=ApprovalTicketResponse)
def approve_action(payload: ApprovalActionRequest, db: Session = Depends(get_db)) -> ApprovalTicketResponse:
    ticket = get_approval_ticket(db, payload.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="approval ticket not found")
    ticket = update_approval_ticket_status(db, ticket, status="approved", actor_id=payload.actor_id)
    return ApprovalTicketResponse(
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        action_type=ticket.action_type,
        status=ticket.status,
        actor_id=ticket.actor_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@app.post("/api/actions/reject", response_model=ApprovalTicketResponse)
def reject_action(payload: ApprovalActionRequest, db: Session = Depends(get_db)) -> ApprovalTicketResponse:
    ticket = get_approval_ticket(db, payload.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="approval ticket not found")
    ticket = update_approval_ticket_status(db, ticket, status="rejected", actor_id=payload.actor_id)
    return ApprovalTicketResponse(
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        action_type=ticket.action_type,
        status=ticket.status,
        actor_id=ticket.actor_id,
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
