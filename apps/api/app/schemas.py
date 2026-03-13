from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class HealthResponse(BaseModel):
    status: str
    environment: str
    local_llm_provider: str
    local_llm_base_url: str
    database_status: str


class ChatRequest(BaseModel):
    message: str
    channel: str = "web"
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    route: str
    local_llm_provider: str
    model: str
    session_id: str


class KakaoWebhookUser(BaseModel):
    id: str | None = None


class KakaoWebhookIntent(BaseModel):
    id: str | None = None
    name: str | None = None


class KakaoWebhookUtterance(BaseModel):
    utterance: str
    user_request_id: str | None = Field(default=None, alias="userRequestId")
    callback_url: str | None = Field(default=None, alias="callbackUrl")
    user: KakaoWebhookUser | None = None
    intent: KakaoWebhookIntent | None = None


class KakaoSimpleText(BaseModel):
    text: str


class KakaoSimpleTextOutput(BaseModel):
    simpleText: KakaoSimpleText


class KakaoButton(BaseModel):
    action: str
    label: str
    web_link_url: str | None = Field(default=None, alias="webLinkUrl")
    message_text: str | None = Field(default=None, alias="messageText")


class KakaoBasicCard(BaseModel):
    title: str
    description: str
    buttons: list[KakaoButton] | None = None


class KakaoBasicCardOutput(BaseModel):
    basicCard: KakaoBasicCard


class KakaoQuickReply(BaseModel):
    label: str
    action: str
    message_text: str | None = Field(default=None, alias="messageText")


class KakaoTemplate(BaseModel):
    outputs: list[KakaoSimpleTextOutput | KakaoBasicCardOutput]
    quick_replies: list[KakaoQuickReply] | None = Field(default=None, alias="quickReplies")


class KakaoWebhookResponse(BaseModel):
    version: str = "2.0"
    use_callback: bool = Field(default=False, alias="useCallback")
    data: dict[str, str] | None = None
    template: KakaoTemplate


class SessionResponse(BaseModel):
    session_id: str
    user_id: str | None
    channel: str
    status: str
    summary: str | None
    last_message: str | None
    created_at: datetime
    updated_at: datetime


class TaskResponse(BaseModel):
    task_id: str
    session_id: str | None
    status: str
    task_type: str
    detail: str | None
    created_at: datetime
    updated_at: datetime


class ApprovalActionRequest(BaseModel):
    ticket_id: str
    actor_id: str | None = None


class ApprovalTicketResponse(BaseModel):
    ticket_id: str
    session_id: str | None
    action_type: str
    status: str
    actor_id: str | None
    created_at: datetime
    updated_at: datetime
