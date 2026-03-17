from datetime import datetime
from typing import Any

from pydantic import ConfigDict
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
    user_id: str | None = Field(default=None, alias="userId")


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
    user_id: str | None = Field(default=None, alias="userId")
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
    callback_url: str | None = Field(default=None, alias="callbackUrl")
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

    def resolved_callback_url(self) -> str | None:
        if self.callback_url:
            return self.callback_url
        if self.user_request and self.user_request.callback_url:
            return self.user_request.callback_url
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


class KakaoThumbnail(BaseModel):
    image_url: str = Field(alias="imageUrl")
    alt_text: str | None = Field(default=None, alias="altText")


class KakaoBasicCard(BaseModel):
    title: str
    description: str
    thumbnail: KakaoThumbnail
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
    template: KakaoTemplate | None = None


class ExtractionReference(BaseModel):
    reference_type: str = Field(alias="referenceType")
    reference_id: str | None = Field(default=None, alias="referenceId")
    label: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class CalendarExtractionPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    search_title: str | None = Field(default=None, alias="searchTitle")
    date: str | None = None
    start_at: str | None = Field(default=None, alias="startAt")
    end_at: str | None = Field(default=None, alias="endAt")
    search_time_min: str | None = Field(default=None, alias="searchTimeMin")
    search_time_max: str | None = Field(default=None, alias="searchTimeMax")
    timezone: str | None = None


class MailExtractionPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reply_mode: str | None = Field(default=None, alias="replyMode")
    recipients: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    sender: str | None = None
    subject: str | None = None
    body: str | None = None
    thread_reference: str | None = Field(default=None, alias="threadReference")
    message_reference: str | None = Field(default=None, alias="messageReference")
    search_query: str | None = Field(default=None, alias="searchQuery")
    attachment_urls: list[str] = Field(default_factory=list, alias="attachmentUrls")


class NoteExtractionPayload(BaseModel):
    title: str | None = None
    body: str | None = None
    folder: str | None = None


class StructuredExtraction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str = "1"
    raw_message: str = Field(alias="rawMessage")
    normalized_message: str = Field(alias="normalizedMessage")
    channel: str | None = None
    domain: str
    action: str
    intent: str
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    needs_clarification: bool = Field(default=False, alias="needsClarification")
    approval_required: bool = Field(default=False, alias="approvalRequired")
    missing_fields: list[str] = Field(default_factory=list, alias="missingFields")
    references: list[ExtractionReference] = Field(default_factory=list)
    calendar: CalendarExtractionPayload | None = None
    mail: MailExtractionPayload | None = None
    note: NoteExtractionPayload | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    session_id: str
    user_id: str | None
    channel: str
    status: str
    summary: str | None
    last_message: str | None
    created_at: datetime
    updated_at: datetime


class SessionMessageResponse(BaseModel):
    message_id: str = Field(alias="messageId")
    session_id: str = Field(alias="sessionId")
    role: str
    channel: str | None = None
    message_text: str | None = Field(default=None, alias="messageText")
    route: str | None = None
    structured_data: dict[str, Any] | None = Field(default=None, alias="structuredData")
    message_meta: dict[str, Any] | None = Field(default=None, alias="messageMeta")
    created_at: datetime = Field(alias="createdAt")


class SessionStateResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    last_intent: str | None = Field(default=None, alias="lastIntent")
    last_route: str | None = Field(default=None, alias="lastRoute")
    pending_action: str | None = Field(default=None, alias="pendingAction")
    pending_ticket_id: str | None = Field(default=None, alias="pendingTicketId")
    last_extraction: dict[str, Any] | None = Field(default=None, alias="lastExtraction")
    last_candidates: list[Any] | None = Field(default=None, alias="lastCandidates")
    state_data: dict[str, Any] | None = Field(default=None, alias="stateData")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


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


class UserIdentityRequest(BaseModel):
    internal_user_id: str | None = Field(default=None, alias="internalUserId")
    channel: str
    external_user_id: str = Field(alias="externalUserId")
    display_name: str | None = Field(default=None, alias="displayName")


class UserIdentityResponse(BaseModel):
    identity_id: str = Field(alias="identityId")
    internal_user_id: str = Field(alias="internalUserId")
    channel: str
    external_user_id: str = Field(alias="externalUserId")
    display_name: str | None = Field(default=None, alias="displayName")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UserMemoryCreateRequest(BaseModel):
    category: str = "general"
    content: str
    source: str = "manual"
    memory_meta: dict[str, Any] | None = Field(default=None, alias="memoryMeta")


class UserMemoryUpdateRequest(BaseModel):
    category: str | None = None
    content: str | None = None
    source: str | None = None
    memory_meta: dict[str, Any] | None = Field(default=None, alias="memoryMeta")


class UserMemoryResponse(BaseModel):
    memory_id: str = Field(alias="memoryId")
    internal_user_id: str = Field(alias="internalUserId")
    category: str
    content: str
    source: str
    memory_meta: dict[str, Any] | None = Field(default=None, alias="memoryMeta")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
