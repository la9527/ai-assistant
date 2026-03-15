from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssistantMessage
from app.models import ApprovalTicket
from app.models import AssistantSession
from app.models import SessionState
from app.models import TaskRun


_UNSET = object()


def get_session_by_id(db: Session, session_id: str) -> AssistantSession | None:
    return db.get(AssistantSession, session_id)


def create_session(db: Session, channel: str, user_id: str | None, message: str) -> AssistantSession:
    session = AssistantSession(channel=channel, user_id=user_id, last_message=message)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def update_session_message(db: Session, session: AssistantSession, message: str) -> AssistantSession:
    session.last_message = message
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def create_session_message(
    db: Session,
    session_id: str,
    role: str,
    channel: str | None,
    message_text: str | None,
    route: str | None = None,
    structured_data: dict | None = None,
    message_meta: dict | None = None,
) -> AssistantMessage:
    message = AssistantMessage(
        session_id=session_id,
        role=role,
        channel=channel,
        message_text=message_text,
        route=route,
        structured_data=structured_data,
        message_meta=message_meta,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_session_messages(db: Session, session_id: str, limit: int = 20) -> list[AssistantMessage]:
    stmt = (
        select(AssistantMessage)
        .where(AssistantMessage.session_id == session_id)
        .order_by(desc(AssistantMessage.created_at))
        .limit(limit)
    )
    messages = list(db.execute(stmt).scalars().all())
    messages.reverse()
    return messages


def get_session_state(db: Session, session_id: str) -> SessionState | None:
    return db.get(SessionState, session_id)


def upsert_session_state(
    db: Session,
    session_id: str,
    last_intent: str | None = None,
    last_route: str | None = None,
    pending_action: str | None | object = _UNSET,
    pending_ticket_id: str | None | object = _UNSET,
    last_extraction: dict | None = None,
    last_candidates: list | None | object = _UNSET,
    state_data: dict | None = None,
) -> SessionState:
    state = db.get(SessionState, session_id)
    if state is None:
        state = SessionState(session_id=session_id)

    if last_intent is not None:
        state.last_intent = last_intent
    if last_route is not None:
        state.last_route = last_route
    if pending_action is not _UNSET:
        state.pending_action = pending_action
    if pending_ticket_id is not _UNSET:
        state.pending_ticket_id = pending_ticket_id
    if last_extraction is not None:
        state.last_extraction = last_extraction
    if last_candidates is not _UNSET:
        state.last_candidates = last_candidates
    if state_data is not None:
        merged_state = dict(state.state_data or {})
        merged_state.update(state_data)
        state.state_data = merged_state

    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def create_task_run(
    db: Session,
    session_id: str | None,
    task_type: str,
    detail: str | None,
    status: str = "completed",
) -> TaskRun:
    task = TaskRun(session_id=session_id, task_type=task_type, detail=detail, status=status)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_run(db: Session, task_id: str) -> TaskRun | None:
    return db.get(TaskRun, task_id)


def get_latest_task_run(
    db: Session,
    session_id: str,
    task_type: str | None = None,
    status: str | None = None,
) -> TaskRun | None:
    stmt = select(TaskRun).where(TaskRun.session_id == session_id)
    if task_type is not None:
        stmt = stmt.where(TaskRun.task_type == task_type)
    if status is not None:
        stmt = stmt.where(TaskRun.status == status)
    stmt = stmt.order_by(desc(TaskRun.created_at)).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def update_task_run_status(db: Session, task: TaskRun, status: str, detail: str | None = None) -> TaskRun:
    task.status = status
    if detail is not None:
        task.detail = detail
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_approval_ticket(db: Session, ticket_id: str) -> ApprovalTicket | None:
    return db.get(ApprovalTicket, ticket_id)


def create_approval_ticket(db: Session, session_id: str | None, action_type: str) -> ApprovalTicket:
    ticket = ApprovalTicket(session_id=session_id, action_type=action_type)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_approval_ticket_status(
    db: Session, ticket: ApprovalTicket, status: str, actor_id: str | None
) -> ApprovalTicket:
    ticket.status = status
    ticket.actor_id = actor_id
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def has_pending_approval_ticket(db: Session) -> bool:
    stmt = select(ApprovalTicket.id).where(ApprovalTicket.status == "pending").limit(1)
    return db.execute(stmt).scalar_one_or_none() is not None