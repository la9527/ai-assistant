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
    approval_ticket_id: str | None = None


class BrowserReadRequest(BaseModel):
    url: str
    session_id: str | None = None
    channel: str = "web"
    wait_selector: str | None = Field(default=None, alias="waitSelector")
    timeout_ms: int = Field(default=15000, alias="timeoutMs", ge=1000, le=60000)
    max_chars: int = Field(default=4000, alias="maxChars", ge=500, le=12000)


class BrowserReadResponse(BaseModel):
    session_id: str
    task_id: str = Field(alias="taskId")
    route: str
    url: str
    final_url: str = Field(alias="finalUrl")
    title: str
    description: str | None = None
    headings: list[str]
    content_excerpt: str = Field(alias="contentExcerpt")
    fetched_at: datetime = Field(alias="fetchedAt")


class KakaoWebhookUser(BaseModel):
    id: str | None = None


class KakaoWebhookUserProperties(BaseModel):
    plusfriend_user_key: str | None = Field(default=None, alias="plusfriendUserKey")
    bot_user_key: str | None = Field(default=None, alias="botUserKey")
    app_user_id: str | None = Field(default=None, alias="appUserId")
    is_friend: bool | None = Field(default=None, alias="isFriend")


class KakaoWebhookRequestUser(BaseModel):
    id: str | None = None
    type: str | None = None
    properties: KakaoWebhookUserProperties | None = None


class KakaoWebhookUserRequestBlock(BaseModel):
    id: str | None = None
    name: str | None = None


class KakaoWebhookUserRequest(BaseModel):
    block: KakaoWebhookUserRequestBlock | None = None
    user: KakaoWebhookRequestUser | None = None
    utterance: str | None = None
    lang: str | None = None
    timezone: str | None = None
    params: dict[str, str] | None = None


class KakaoWebhookAction(BaseModel):
    id: str | None = None
    name: str | None = None
    params: dict[str, str] | None = None
    detail_params: dict[str, dict[str, str]] | None = Field(default=None, alias="detailParams")
    client_extra: dict[str, str] | None = Field(default=None, alias="clientExtra")


class KakaoWebhookIntent(BaseModel):
    id: str | None = None
    name: str | None = None


class KakaoWebhookUtterance(BaseModel):
    utterance: str | None = None
    user_request_id: str | None = Field(default=None, alias="userRequestId")
    callback_url: str | None = Field(default=None, alias="callbackUrl")
    user: KakaoWebhookUser | None = None
    intent: KakaoWebhookIntent | None = None
    user_request: KakaoWebhookUserRequest | None = Field(default=None, alias="userRequest")
    action: KakaoWebhookAction | None = None
    bot: dict[str, str] | None = None

    def resolved_utterance(self) -> str | None:
        if self.utterance:
            return self.utterance
        if self.user_request and self.user_request.utterance:
            return self.user_request.utterance
        return None

    def resolved_user_id(self) -> str | None:
        if self.user and self.user.id:
            return self.user.id
        if self.user_request and self.user_request.user and self.user_request.user.id:
            return self.user_request.user.id
        return None


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
    execution_reply: str | None = None
    route: str | None = None
    created_at: datetime
    updated_at: datetime
