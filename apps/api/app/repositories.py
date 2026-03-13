from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalTicket
from app.models import AssistantSession
from app.models import TaskRun


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