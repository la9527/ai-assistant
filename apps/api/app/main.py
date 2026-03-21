import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import time
import uuid
from urllib.parse import parse_qs

from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi import Cookie
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse

import httpx

from app.automation import classify_message_intent
from app.automation import apply_reference_context
from app.automation import extract_candidates_from_reply
from app.automation import extract_user_memory_candidates
from app.automation import extract_structured_request
from app.automation import process_message
from app.config import settings
from app.db import Base
from app.db import engine
from app.db import get_db
from app.db import SessionLocal
from app.llm import format_gmail_action_reply
from app.llm import warm_local_llm
from app.models import ApprovalTicket
from app.models import AssistantSession
from app.models import TaskRun
from app.repositories import create_session_message
from app.repositories import create_user_memory
from app.repositories import create_approval_ticket
from app.repositories import create_session
from app.repositories import create_task_run
from app.repositories import delete_user_memory
from app.repositories import get_approval_ticket
from app.repositories import get_latest_session_for_user
from app.repositories import get_latest_task_run
from app.repositories import get_user_memory
from app.repositories import get_session_by_id
from app.repositories import get_session_state
from app.repositories import get_task_run
from app.repositories import link_user_identity
from app.repositories import list_user_memories
from app.repositories import list_user_identities
from app.repositories import list_session_messages
from app.repositories import resolve_user_identity
from app.repositories import search_user_identities
from app.repositories import update_task_run_status
from app.repositories import update_approval_ticket_status
from app.repositories import update_user_memory
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
from app.schemas import UserIdentityRequest
from app.schemas import UserIdentityResponse
from app.schemas import UserMemoryCreateRequest
from app.schemas import UserMemoryResponse
from app.schemas import UserMemoryUpdateRequest


app = FastAPI(title="AI Assistant API", version="0.1.0")

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Rate Limiting (slowapi)
# ---------------------------------------------------------------------------
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    _limiter_available = True
except ImportError:
    _limiter_available = False

# ---------------------------------------------------------------------------
# API Key Authentication Middleware
# ---------------------------------------------------------------------------
# API_KEY 가 설정되면 아래 경로를 제외한 모든 요청에 X-API-Key 헤더 검증
_AUTH_EXEMPT_PREFIXES = (
    "/api/health",
    "/api/kakao/",
    "/api/slack/",
    "/docs",
    "/openapi.json",
    "/health",
)


@app.middleware("http")
async def api_key_auth_middleware(request: Request, call_next):
    if settings.api_key:
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in _AUTH_EXEMPT_PREFIXES):
            # X-API-Key 헤더 또는 Authorization: Bearer 토큰 둘 다 허용
            provided = request.headers.get("X-API-Key", "")
            if not provided:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    provided = auth_header[7:]
            if not hmac.compare_digest(provided, settings.api_key):
                return Response(
                    content=json.dumps({"detail": "Invalid or missing API key"}),
                    status_code=401,
                    media_type="application/json",
                )
    return await call_next(request)

ADMIN_SESSION_COOKIE = "ai_assistant_admin_session"
ADMIN_SESSION_SECRET = settings.resolved_admin_session_secret

SLACK_CHANNEL_NAME_CACHE: dict[str, str] = {}

APPROVE_PATTERN = re.compile(r"^(승인|approve)\s+([a-zA-Z0-9-]+)$", re.IGNORECASE)
REJECT_PATTERN = re.compile(r"^(거절|reject)\s+([a-zA-Z0-9-]+)$", re.IGNORECASE)
IMPLICIT_APPROVE_PATTERN = re.compile(r"^(승인|진행해|진행해줘|진행해 줘|실행해|실행해줘|실행해 줘|좋아|ok|okay)$", re.IGNORECASE)
IMPLICIT_REJECT_PATTERN = re.compile(r"^(거절|취소|취소해|취소해줘|취소해 줘|중단|그만)$", re.IGNORECASE)
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
    if user_id:
        session = get_latest_session_for_user(db, user_id)
        if session is not None:
            return update_session_message(db, session, utterance)
    return create_session(db, channel="kakao", user_id=user_id, message=utterance, session_id=session_id)


def _resolve_internal_user_id(
    db: Session,
    channel: str,
    external_user_id: str | None,
    display_name: str | None = None,
) -> str | None:
    if not external_user_id:
        return None
    identity = resolve_user_identity(db, channel, external_user_id, display_name)
    return identity.internal_user_id


def _resolve_channel_session(
    db: Session,
    channel: str,
    session_id: str | None,
    internal_user_id: str | None,
    message: str,
) -> AssistantSession:
    if session_id:
        session = get_session_by_id(db, session_id)
        if session is not None:
            return update_session_message(db, session, message)
    if internal_user_id:
        session = get_latest_session_for_user(db, internal_user_id)
        if session is not None:
            return update_session_message(db, session, message)
    return create_session(db, channel=channel, user_id=internal_user_id, message=message, session_id=session_id)


def _user_identity_response(identity) -> UserIdentityResponse:
    return UserIdentityResponse(
        identityId=identity.id,
        internalUserId=identity.internal_user_id,
        channel=identity.channel,
        externalUserId=identity.external_user_id,
        displayName=identity.display_name,
        createdAt=identity.created_at,
        updatedAt=identity.updated_at,
    )


def _user_memory_response(memory) -> UserMemoryResponse:
    return UserMemoryResponse(
        memoryId=memory.id,
        internalUserId=memory.internal_user_id,
        category=memory.category,
        content=memory.content,
        source=memory.source,
        memoryMeta=memory.memory_meta,
        createdAt=memory.created_at,
        updatedAt=memory.updated_at,
    )


def _load_user_memory_context(db: Session, internal_user_id: str | None, limit: int = 6) -> list[dict[str, str]]:
    if not internal_user_id:
        return []
    memories = list_user_memories(db, internal_user_id, limit=limit)
    return [
        {
            "category": memory.category,
            "content": memory.content,
            "source": memory.source,
        }
        for memory in memories
    ]


def _persist_automatic_user_memories(db: Session, internal_user_id: str | None, message: str) -> None:
    if not internal_user_id:
        return
    existing_memories = list_user_memories(db, internal_user_id, limit=20)
    existing_pairs = {(item.category, item.content.strip()) for item in existing_memories if item.content}
    for candidate in extract_user_memory_candidates(message):
        key = (candidate["category"], candidate["content"].strip())
        if key in existing_pairs:
            continue
        create_user_memory(
            db,
            internal_user_id,
            candidate["category"],
            candidate["content"],
            source=candidate["source"],
            memory_meta={"captured_from": "message_rule"},
        )
        existing_pairs.add(key)


def _admin_auth_enabled() -> bool:
    return settings.admin_auth_enabled


def _build_admin_session_token() -> str:
    issued_at = int(time.time())
    expires_at = issued_at + max(300, settings.admin_session_ttl_seconds)
    nonce = secrets.token_urlsafe(16)
    payload = f"{issued_at}:{expires_at}:{nonce}"
    signature = hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _is_admin_session_valid(token: str | None) -> bool:
    if not _admin_auth_enabled():
        return True
    if not token:
        return False
    try:
        issued_at_str, expires_at_str, nonce, signature = token.split(":", 3)
        payload = f"{issued_at_str}:{expires_at_str}:{nonce}"
        expected_signature = hmac.new(
            ADMIN_SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return False
        if int(expires_at_str) < int(time.time()):
            return False
        return True
    except Exception:
        return False


def _is_admin_login_valid(username: str, password: str) -> bool:
    if not _admin_auth_enabled():
        return True
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(password, settings.admin_password)


def _require_admin_access(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE),
) -> None:
    if _is_admin_session_valid(admin_session):
        return
    raise HTTPException(status_code=401, detail="admin login required")


def _render_admin_login_page(error_message: str | None = None) -> str:
    error_html = f'<p style="color:#b91c1c;">{html.escape(error_message)}</p>' if error_message else ""
    return """<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>AI Assistant Admin Login</title>
  <style>
    body { margin:0; min-height:100vh; display:grid; place-items:center; background:linear-gradient(160deg,#fff7ed,#f3efe6 55%,#efe7db); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:#1f2937; }
        form { width:min(420px, calc(100vw - 32px)); background:#fffdf8; border:1px solid #d6cfc2; border-radius:20px; padding:24px; box-shadow:0 14px 40px rgba(120,53,15,.12); }
    h1 { margin:0 0 12px; font-size:22px; }
    p { margin:0 0 14px; color:#6b7280; }
    input { width:100%; box-sizing:border-box; padding:12px 14px; border:1px solid #d6cfc2; border-radius:12px; }
    button { margin-top:12px; width:100%; padding:12px 14px; border:0; border-radius:999px; background:#9a3412; color:#fff; font:inherit; cursor:pointer; }
  </style>
</head>
<body>
    <form id=\"admin-login-form\">
        <h1>관리자 로그인</h1>
        <p>`ADMIN_USERNAME`, `ADMIN_PASSWORD` 가 설정된 환경입니다. 로그인하면 서버가 관리자 세션 토큰을 자동 발급합니다.</p>
        __ERROR_HTML__
        <input type=\"text\" id=\"username\" placeholder=\"admin id\" autofocus />
        <input type=\"password\" id=\"password\" placeholder=\"password\" style=\"margin-top:12px;\" />
        <button type=\"submit\">로그인</button>
  </form>
    <script>
        document.getElementById('admin-login-form').addEventListener('submit', async (event) => {
            event.preventDefault();
            const response = await fetch('/assistant/api/admin/session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value,
                }),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                alert(body.detail || '로그인에 실패했습니다.');
                return;
            }
            window.location.href = '/assistant/api/admin/users';
        });
    </script>
</body>
</html>""".replace("__ERROR_HTML__", error_html)


def _render_admin_users_page() -> str:
    return f"""<!doctype html>
<html lang=\"ko\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>AI Assistant Admin</title>
    <style>
        :root {{ color-scheme: light; --bg:#f3efe6; --panel:#fffdf8; --ink:#1f2937; --muted:#6b7280; --line:#d6cfc2; --accent:#9a3412; --accent-soft:#ffedd5; }}
        body {{ margin:0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: radial-gradient(circle at top, #fff7ed 0%, var(--bg) 55%, #efe7db 100%); color:var(--ink); }}
        main {{ max-width:1200px; margin:0 auto; padding:32px 20px 56px; }}
        h1, h2 {{ margin:0 0 12px; }}
        p {{ margin:0 0 14px; color:var(--muted); }}
        .grid {{ display:grid; gap:16px; grid-template-columns: 1.1fr 0.9fr; }}
        .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow: 0 10px 40px rgba(120, 53, 15, 0.08); }}
        .stack {{ display:grid; gap:12px; }}
        label {{ display:grid; gap:6px; font-size:13px; color:var(--muted); }}
        input, textarea, select, button {{ font: inherit; }}
        input, textarea, select {{ width:100%; box-sizing:border-box; padding:10px 12px; border:1px solid var(--line); border-radius:12px; background:white; color:var(--ink); }}
        textarea {{ min-height:96px; resize:vertical; }}
        button {{ border:0; border-radius:999px; padding:10px 14px; background:var(--accent); color:white; cursor:pointer; }}
        button.secondary {{ background:var(--accent-soft); color:var(--accent); }}
        table {{ width:100%; border-collapse: collapse; font-size:13px; }}
        th, td {{ padding:10px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
        th {{ color:var(--muted); font-weight:600; }}
        .row {{ display:flex; gap:8px; flex-wrap:wrap; }}
        .badge {{ display:inline-block; padding:4px 8px; border-radius:999px; background:var(--accent-soft); color:var(--accent); font-size:12px; }}
        .muted {{ color:var(--muted); }}
        .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break:break-all; }}
        .selected {{ background:#fff7ed; }}
        @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
<main>
    <div class=\"panel\" style=\"margin-bottom:16px\">
        <h1>사용자 매핑 및 장기 메모리</h1>
        <p>채널 외부 ID를 공통 내부 사용자 ID로 묶고, 같은 사용자에게 적용되는 장기 메모리를 수동으로 관리합니다.</p>
        <div class=\"row\"><span class=\"badge\">Tailscale 내부 관리자용</span><span class=\"badge\">FastAPI 내장 UI</span></div>
    </div>
    <div class=\"grid\">
        <section class=\"panel stack\">
            <div>
                <h2>Identity 검색</h2>
                <p>외부 ID 일부나 내부 사용자 ID로 조회한 뒤, 선택한 사용자에게 새 채널 ID를 연결할 수 있습니다.</p>
            </div>
            <div class=\"row\">
                <label style=\"flex:1 1 180px\">channel<input id=\"search-channel\" placeholder=\"slack / kakao / web\" /></label>
                <label style=\"flex:1 1 220px\">external user<input id=\"search-external\" placeholder=\"U123 / kakao-user-key\" /></label>
                <label style=\"flex:1 1 220px\">internal user<input id=\"search-internal\" placeholder=\"uuid\" /></label>
            </div>
            <div class=\"row\">
                <button id=\"search-button\">조회</button>
                <button id=\"recent-button\" class=\"secondary\">최근 항목</button>
            </div>
            <div id=\"search-status\" class=\"muted\"></div>
            <table>
                <thead><tr><th>internal</th><th>channel</th><th>external</th><th>display</th><th></th></tr></thead>
                <tbody id=\"identity-results\"></tbody>
            </table>
        </section>
        <section class=\"panel stack\">
            <div>
                <h2>선택된 사용자</h2>
                <p id=\"selected-user\" class=\"mono muted\">선택된 내부 사용자 없음</p>
            </div>
            <div class=\"stack\">
                <h2>Identity 연결</h2>
                <label>internal user<input id=\"link-internal\" placeholder=\"선택 시 자동 입력\" /></label>
                <label>channel<input id=\"link-channel\" placeholder=\"slack / kakao / web\" /></label>
                <label>external user<input id=\"link-external\" /></label>
                <label>display name<input id=\"link-display\" /></label>
                <div class=\"row\">
                    <button id=\"link-button\">연결 저장</button>
                    <button id=\"resolve-button\" class=\"secondary\">단독 resolve</button>
                </div>
            </div>
            <div id=\"identity-list\" class=\"stack\"></div>
        </section>
    </div>
    <div class=\"grid\" style=\"margin-top:16px\">
        <section class=\"panel stack\">
            <div>
                <h2>장기 메모리 등록</h2>
                <p>선택한 내부 사용자에 대해 장기적으로 유지할 사실, 선호, 운영 메모를 저장합니다.</p>
            </div>
            <label>internal user<input id=\"memory-internal\" placeholder=\"선택 시 자동 입력\" /></label>
            <div class=\"row\">
                <label style=\"flex:1 1 180px\">category<input id=\"memory-category\" value=\"preference\" /></label>
                <label style=\"flex:1 1 180px\">source<input id=\"memory-source\" value=\"manual\" /></label>
            </div>
            <label>content<textarea id=\"memory-content\" placeholder=\"예: 같은 사용자는 일정 요약을 오전 기준으로 짧게 받길 선호함\"></textarea></label>
            <div class=\"row\"><button id=\"memory-create\">메모 저장</button></div>
            <div id=\"memory-status\" class=\"muted\"></div>
        </section>
        <section class=\"panel stack\">
            <div>
                <h2>메모 목록</h2>
                <p>선택한 내부 사용자에 저장된 최근 장기 메모입니다. 삭제는 즉시 반영됩니다.</p>
            </div>
            <div id=\"memory-list\" class=\"stack\"></div>
        </section>
    </div>
</main>
<script>
    const apiBase = window.location.pathname.replace(/\\/admin\\/users\\/?$/, '');
    let selectedInternalUserId = '';

    function esc(value) {{
        return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    }}

    function setSelectedUser(internalUserId) {{
        selectedInternalUserId = internalUserId || '';
        document.getElementById('selected-user').textContent = selectedInternalUserId || '선택된 내부 사용자 없음';
        document.getElementById('link-internal').value = selectedInternalUserId;
        document.getElementById('memory-internal').value = selectedInternalUserId;
        if (selectedInternalUserId) {{
            loadIdentityAliases();
            loadMemories();
        }} else {{
            document.getElementById('identity-list').innerHTML = '';
            document.getElementById('memory-list').innerHTML = '';
        }}
    }}

    async function loadIdentityResults(params = '') {{
        const status = document.getElementById('search-status');
        status.textContent = '조회 중...';
        const response = await fetch(`${{apiBase}}/users/identities${{params}}`, {{ credentials: 'include' }});
        const data = await response.json();
        const body = document.getElementById('identity-results');
        body.innerHTML = data.map((item) => `
            <tr class="${{item.internalUserId === selectedInternalUserId ? 'selected' : ''}}">
                <td class="mono">${{esc(item.internalUserId)}}</td>
                <td>${{esc(item.channel)}}</td>
                <td class="mono">${{esc(item.externalUserId)}}</td>
                <td>${{esc(item.displayName || '')}}</td>
                <td><button class="secondary" onclick="setSelectedUser('${{esc(item.internalUserId)}}')">선택</button></td>
            </tr>
        `).join('');
        status.textContent = `조회 결과 ${{data.length}}건`;
    }}

    async function loadIdentityAliases() {{
        if (!selectedInternalUserId) return;
        const response = await fetch(`${{apiBase}}/users/${{encodeURIComponent(selectedInternalUserId)}}/identities`, {{ credentials: 'include' }});
        const data = await response.json();
        const el = document.getElementById('identity-list');
        el.innerHTML = `<div class="muted">연결된 identity ${{data.length}}건</div>` + data.map((item) => `
            <div class="panel" style="padding:12px; border-radius:14px; box-shadow:none;">
                <div class="row"><span class="badge">${{esc(item.channel)}}</span><span class="mono">${{esc(item.externalUserId)}}</span></div>
                <div>${{esc(item.displayName || '')}}</div>
            </div>
        `).join('');
    }}

    async function loadMemories() {{
        if (!selectedInternalUserId) return;
        const response = await fetch(`${{apiBase}}/users/${{encodeURIComponent(selectedInternalUserId)}}/memories`, {{ credentials: 'include' }});
        const data = await response.json();
        const el = document.getElementById('memory-list');
        el.innerHTML = data.length ? data.map((item) => `
            <div class="panel" style="padding:12px; border-radius:14px; box-shadow:none;">
                <div class="row"><span class="badge">${{esc(item.category)}}</span><span class="badge">${{esc(item.source)}}</span></div>
                <div style="white-space:pre-wrap">${{esc(item.content)}}</div>
                <div class="row" style="margin-top:8px"><button class="secondary" onclick="deleteMemory('${{esc(item.memoryId)}}')">삭제</button></div>
            </div>
        `).join('') : '<div class="muted">저장된 메모가 없습니다.</div>';
    }}

    async function deleteMemory(memoryId) {{
        await fetch(`${{apiBase}}/users/memories/${{encodeURIComponent(memoryId)}}`, {{ method: 'DELETE', credentials: 'include' }});
        await loadMemories();
    }}

    async function submitLink(resolveOnly) {{
        const payload = {{
            internalUserId: document.getElementById('link-internal').value || null,
            channel: document.getElementById('link-channel').value,
            externalUserId: document.getElementById('link-external').value,
            displayName: document.getElementById('link-display').value || null,
        }};
        const endpoint = resolveOnly ? 'resolve' : 'link';
        const response = await fetch(`${{apiBase}}/users/identities/${{endpoint}}`, {{
            method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, credentials: 'include', body: JSON.stringify(payload)
        }});
        if (!response.ok) {{
            alert(await response.text());
            return;
        }}
        const data = await response.json();
        setSelectedUser(data.internalUserId);
        await loadIdentityResults('?limit=50');
    }}

    async function createMemory() {{
        const internalUserId = document.getElementById('memory-internal').value;
        if (!internalUserId) {{
            alert('먼저 내부 사용자를 선택하거나 입력하세요.');
            return;
        }}
        const payload = {{
            category: document.getElementById('memory-category').value || 'general',
            source: document.getElementById('memory-source').value || 'manual',
            content: document.getElementById('memory-content').value,
        }};
        const response = await fetch(`${{apiBase}}/users/${{encodeURIComponent(internalUserId)}}/memories`, {{
            method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, credentials: 'include', body: JSON.stringify(payload)
        }});
        if (!response.ok) {{
            alert(await response.text());
            return;
        }}
        document.getElementById('memory-content').value = '';
        document.getElementById('memory-status').textContent = '메모를 저장했습니다.';
        setSelectedUser(internalUserId);
    }}

    document.getElementById('search-button').addEventListener('click', async () => {{
        const channel = document.getElementById('search-channel').value;
        const external = document.getElementById('search-external').value;
        const internal = document.getElementById('search-internal').value;
        const params = new URLSearchParams();
        if (channel) params.set('channel', channel);
        if (external) params.set('external_user_id', external);
        if (internal) params.set('internal_user_id', internal);
        params.set('limit', '50');
        await loadIdentityResults(`?${{params.toString()}}`);
    }});
    document.getElementById('recent-button').addEventListener('click', () => loadIdentityResults('?limit=50'));
    document.getElementById('link-button').addEventListener('click', () => submitLink(false));
    document.getElementById('resolve-button').addEventListener('click', () => submitLink(true));
    document.getElementById('memory-create').addEventListener('click', createMemory);
    loadIdentityResults('?limit=50');
</script>
</body>
</html>"""


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
    previous_extraction: StructuredExtraction | None = None,
    last_candidates: list[dict[str, str]] | None = None,
) -> StructuredExtraction:
    extraction = extract_structured_request(message, channel, history)
    return apply_reference_context(extraction, previous_extraction, last_candidates)


def _load_previous_extraction(db: Session, session_id: str) -> StructuredExtraction | None:
    state = get_session_state(db, session_id)
    if state is None or state.last_extraction is None:
        return None
    try:
        return StructuredExtraction.model_validate(state.last_extraction)
    except Exception:
        logger.warning("Failed to validate last extraction for session_id=%s", session_id)
        return None


def _load_last_candidates(db: Session, session_id: str) -> list[dict[str, str]] | None:
    state = get_session_state(db, session_id)
    if state is None or not state.last_candidates:
        return None
    return state.last_candidates


def _match_pending_ticket_command(db: Session, session_id: str, message: str) -> tuple[str, str] | None:
    state = get_session_state(db, session_id)
    if state is None or not state.pending_ticket_id:
        return None
    normalized = message.strip()
    if IMPLICIT_APPROVE_PATTERN.match(normalized):
        return "approve", state.pending_ticket_id
    if IMPLICIT_REJECT_PATTERN.match(normalized):
        return "reject", state.pending_ticket_id
    return None


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
    _persist_automatic_user_memories(db, session.user_id, message)
    return structured_payload or {}


def _record_assistant_message(
    db: Session,
    session_id: str,
    channel: str,
    reply: str,
    route: str,
    action_type: str | None = None,
    approval_ticket_id: str | None = None,
    workflow_candidates: list[dict[str, str]] | None = None,
    workflow_state_data: dict[str, object] | None = None,
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

    # 응답에서 번호 목록이 있으면 후보로 저장 (후보 선택형 후속 대화 지원)
    # 워크플로에서 직접 제공한 후보가 있으면 우선 사용 (gmail items 등 리치 데이터)
    reply_candidates = workflow_candidates or extract_candidates_from_reply(reply, route)

    state_data = {"last_assistant_reply": reply}
    if workflow_state_data:
        state_data.update(workflow_state_data)

    state_kwargs: dict[str, object] = {
        "last_route": route,
        "pending_action": action_type if route == "approval_required" else None,
        "pending_ticket_id": approval_ticket_id if route == "approval_required" else None,
        "state_data": state_data,
    }
    # 새 후보가 없을 때는 이전 후보를 유지해 후속 번호 선택 대화를 지원한다.
    if reply_candidates:
        state_kwargs["last_candidates"] = reply_candidates

    upsert_session_state(
        db,
        session_id=session_id,
        **state_kwargs,
    )


def _process_kakao_message(
    db: Session,
    utterance: str,
    user_id: str | None,
    session_id: str | None = None,
) -> tuple[str, str, str, str | None, str | None]:
    internal_user_id = _resolve_internal_user_id(db, "kakao", user_id)
    approval_command = _match_approval_command(utterance)
    if approval_command is not None:
        return _handle_approval_command(approval_command, internal_user_id, db)

    session = _resolve_channel_session(db, "kakao", session_id, internal_user_id, utterance)
    pending_command = _match_pending_ticket_command(db, session.id, utterance)
    if pending_command is not None:
        return _handle_approval_command(pending_command, internal_user_id, db)

    structured = _build_structured_payload(
        utterance,
        "kakao",
        _session_history_context(db, session.id),
        _load_previous_extraction(db, session.id),
        last_candidates=_load_last_candidates(db, session.id),
    )
    memory_context = _load_user_memory_context(db, internal_user_id)
    _record_user_message(db, session, "kakao", utterance, structured)
    result = process_message(
        utterance,
        "kakao",
        session.id,
        internal_user_id,
        structured_extraction=structured,
        memory_context=memory_context,
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
        reply = f"{result['reply']}\n티켓: {ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=utterance)
        reply = str(result["reply"])

        _record_assistant_message(
            db,
            session.id,
            "kakao",
            reply,
            str(result["route"]),
            action_type,
            approval_ticket_id,
            workflow_candidates=result.get("last_candidates"),
            workflow_state_data={"last_mail_result_context": result.get("mail_result_context")} if result.get("mail_result_context") else None,
        )

    return session.id, reply, str(result["route"]), approval_ticket_id, action_type


def _resolve_kakao_callback_session_id(db: Session, utterance: str, user_id: str | None) -> str:
    approval_command = _match_approval_command(utterance)
    if approval_command is not None:
        ticket = get_approval_ticket(db, approval_command[1])
        if ticket is not None and ticket.session_id:
            return ticket.session_id
        return "unknown"
    internal_user_id = _resolve_internal_user_id(db, "kakao", user_id)
    session = _resolve_channel_session(db, "kakao", None, internal_user_id, utterance)
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
    if _admin_auth_enabled() and not settings.admin_session_secret:
        logger.warning("ADMIN_SESSION_SECRET is not set; using an ephemeral in-memory secret for admin sessions")
    warm_local_llm()
    # MCP 서버 비동기 초기화
    if settings.mcp_servers:
        import asyncio
        from app.mcp.client import MCPServerConfig, initialize_mcp_servers
        from app.mcp.registry import register_mcp_tools
        configs = [MCPServerConfig(**s) for s in settings.mcp_servers]
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_init_mcp(configs))
            else:
                loop.run_until_complete(_init_mcp(configs))
        except Exception:
            logger.warning("MCP 서버 초기화를 건너뜁니다 — 비동기 루프 없음")


async def _init_mcp(configs: list) -> None:
    from app.mcp.client import initialize_mcp_servers
    from app.mcp.registry import register_mcp_tools
    manager = await initialize_mcp_servers(configs)
    register_mcp_tools(manager)


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


@app.get("/api/admin/users", response_class=HTMLResponse)
def admin_users_page(admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE)) -> HTMLResponse:
    if not _is_admin_session_valid(admin_session):
        return HTMLResponse(_render_admin_login_page(), status_code=401)
    return HTMLResponse(_render_admin_users_page())


@app.post("/api/admin/session")
async def create_admin_session(request: Request) -> Response:
    if not _admin_auth_enabled():
        response = Response(status_code=204)
        response.set_cookie(
            ADMIN_SESSION_COOKIE,
            value=_build_admin_session_token(),
            max_age=max(300, settings.admin_session_ttl_seconds),
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
        return response

    payload = await request.json()
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    if not _is_admin_login_valid(username, password):
        raise HTTPException(status_code=401, detail="invalid admin credentials")

    response = Response(status_code=204)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        value=_build_admin_session_token(),
        max_age=max(300, settings.admin_session_ttl_seconds),
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return response


@app.delete("/api/admin/session", status_code=204)
def delete_admin_session() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return response


@app.get("/api/users/identities", response_model=list[UserIdentityResponse])
def search_user_identities_api(
    channel: str | None = None,
    external_user_id: str | None = None,
    internal_user_id: str | None = None,
    limit: int = 50,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> list[UserIdentityResponse]:
    identities = search_user_identities(
        db,
        channel=channel,
        external_user_id=external_user_id,
        internal_user_id=internal_user_id,
        limit=max(1, min(limit, 200)),
    )
    return [_user_identity_response(identity) for identity in identities]


@app.post("/api/users/identities/resolve", response_model=UserIdentityResponse)
def resolve_user_identity_api(
    payload: UserIdentityRequest,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> UserIdentityResponse:
    identity = resolve_user_identity(db, payload.channel, payload.external_user_id, payload.display_name)
    return _user_identity_response(identity)


@app.post("/api/users/identities/link", response_model=UserIdentityResponse)
def link_user_identity_api(
    payload: UserIdentityRequest,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> UserIdentityResponse:
    if not payload.internal_user_id:
        raise HTTPException(status_code=400, detail="internalUserId is required")
    identity = link_user_identity(
        db,
        payload.internal_user_id,
        payload.channel,
        payload.external_user_id,
        payload.display_name,
    )
    return _user_identity_response(identity)


@app.get("/api/users/{internal_user_id}/identities", response_model=list[UserIdentityResponse])
def get_user_identities_api(
    internal_user_id: str,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> list[UserIdentityResponse]:
    return [_user_identity_response(identity) for identity in list_user_identities(db, internal_user_id)]


@app.get("/api/users/{internal_user_id}/memories", response_model=list[UserMemoryResponse])
def get_user_memories_api(
    internal_user_id: str,
    category: str | None = None,
    limit: int = 20,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> list[UserMemoryResponse]:
    memories = list_user_memories(db, internal_user_id, category=category, limit=max(1, min(limit, 100)))
    return [_user_memory_response(memory) for memory in memories]


@app.post("/api/users/{internal_user_id}/memories", response_model=UserMemoryResponse)
def create_user_memory_api(
    internal_user_id: str,
    payload: UserMemoryCreateRequest,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> UserMemoryResponse:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    memory = create_user_memory(
        db,
        internal_user_id,
        payload.category.strip() or "general",
        content,
        source=payload.source.strip() or "manual",
        memory_meta=payload.memory_meta,
    )
    return _user_memory_response(memory)


@app.patch("/api/users/memories/{memory_id}", response_model=UserMemoryResponse)
def update_user_memory_api(
    memory_id: str,
    payload: UserMemoryUpdateRequest,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> UserMemoryResponse:
    memory = get_user_memory(db, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    memory = update_user_memory(
        db,
        memory,
        category=payload.category if payload.category is not None else _UNSET,
        content=payload.content.strip() if payload.content is not None else _UNSET,
        source=payload.source if payload.source is not None else _UNSET,
        memory_meta=payload.memory_meta if payload.memory_meta is not None else _UNSET,
    )
    return _user_memory_response(memory)


@app.delete("/api/users/memories/{memory_id}", status_code=204)
def delete_user_memory_api(
    memory_id: str,
    _: None = Depends(_require_admin_access),
    db: Session = Depends(get_db),
) -> Response:
    memory = get_user_memory(db, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    delete_user_memory(db, memory)
    return Response(status_code=204)


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    return _chat_impl(payload, db)


# slowapi 데코레이터는 런타임에 적용
if _limiter_available:
    chat = limiter.limit(settings.rate_limit_chat)(chat)


def _chat_impl(payload: ChatRequest, db: Session, *, provider_hint: str | None = None) -> ChatResponse:
    internal_user_id = _resolve_internal_user_id(db, payload.channel, payload.user_id)
    memory_context = _load_user_memory_context(db, internal_user_id)
    approval_command = _match_approval_command(payload.message)
    if approval_command is not None:
        session_id, reply, route, approval_ticket_id, _ = _handle_approval_command(approval_command, internal_user_id, db)
        return ChatResponse(
            reply=reply,
            route=route,
            local_llm_provider=settings.local_llm.provider,
            model=settings.local_llm.model,
            session_id=session_id,
            approval_ticket_id=approval_ticket_id,
        )

    session = _resolve_channel_session(db, payload.channel, payload.session_id, internal_user_id, payload.message)

    pending_command = _match_pending_ticket_command(db, session.id, payload.message)
    if pending_command is not None:
        session_id, reply, route, approval_ticket_id, _ = _handle_approval_command(pending_command, internal_user_id, db)
        return ChatResponse(
            reply=reply,
            route=route,
            local_llm_provider=settings.local_llm.provider,
            model=settings.local_llm.model,
            session_id=session_id,
            approval_ticket_id=approval_ticket_id,
        )

    structured = _build_structured_payload(
        payload.message,
        payload.channel,
        _session_history_context(db, session.id),
        _load_previous_extraction(db, session.id),
        last_candidates=_load_last_candidates(db, session.id),
    )
    _record_user_message(db, session, payload.channel, payload.message, structured)

    result = process_message(
        payload.message,
        payload.channel,
        session.id,
        internal_user_id,
        structured_extraction=structured,
        memory_context=memory_context,
        provider_hint=provider_hint,
    )
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
        reply = f"{result['reply']}\n티켓: {ticket.id}"
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
        workflow_candidates=result.get("last_candidates"),
            workflow_state_data={"last_mail_result_context": result.get("mail_result_context")} if result.get("mail_result_context") else None,
    )
    return ChatResponse(
        reply=reply,
        route=str(result["route"]),
        local_llm_provider=settings.local_llm.provider,
        model=settings.local_llm.model,
        session_id=session.id,
        approval_ticket_id=approval_ticket_id,
    )


# ---------------------------------------------------------------------------
# OpenAI-compatible API  (/v1/chat/completions, /v1/models)
# Open WebUI 등 OpenAI 호환 클라이언트에서 직접 연결할 수 있는 프록시 엔드포인트.
# 일반 채팅은 로컬/외부 LLM으로 포워딩하고, 자동화 의도가 감지되면
# 기존 파이프라인(LangGraph → n8n → 승인)을 실행한 뒤 결과를 OpenAI 응답
# 형식으로 wrapping한다.
# ---------------------------------------------------------------------------

_OPENAI_COMPAT_MODEL = "ai-assistant"
_OPENAI_COMPAT_MODEL_PREFIX = "ai-assistant:"

_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Claude",
    "gemini": "Gemini",
}


def _openai_chat_response(
    reply: str,
    model: str = _OPENAI_COMPAT_MODEL,
    finish_reason: str = "stop",
) -> dict[str, object]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _openai_stream_chunks(
    reply: str,
    model: str = _OPENAI_COMPAT_MODEL,
) -> list[str]:
    """응답 텍스트를 SSE 청크 목록으로 변환한다."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    chunks: list[str] = []
    # 역할 청크
    chunks.append(json.dumps({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }, ensure_ascii=False))
    # 내용 청크 — 문장 단위로 분할
    sentences = re.split(r"(?<=[.!?。\n])\s*", reply)
    for sentence in sentences:
        if not sentence:
            continue
        chunks.append(json.dumps({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": sentence}, "finish_reason": None}],
        }, ensure_ascii=False))
    # 종료 청크
    chunks.append(json.dumps({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }, ensure_ascii=False))
    return chunks


@app.get("/v1/models")
def openai_list_models() -> dict:
    """OpenAI 호환 모델 목록. Open WebUI 모델 선택 드롭다운에 표시된다."""
    models = [
        {
            "id": _OPENAI_COMPAT_MODEL,
            "object": "model",
            "created": 1700000000,
            "owned_by": "ai-assistant",
        },
    ]
    # 외부 LLM provider별 모델 추가
    for prov_info in settings.available_external_providers():
        prov = prov_info["provider"]
        display = _PROVIDER_DISPLAY_NAMES.get(prov, prov)
        models.append({
            "id": f"{_OPENAI_COMPAT_MODEL}:{prov}",
            "object": "model",
            "created": 1700000000,
            "owned_by": f"ai-assistant/{display}",
        })
    # 로컬 MLX 모델도 노출하여 직접 대화 가능
    if settings.local_llm.model:
        models.append({
            "id": settings.local_llm.model,
            "object": "model",
            "created": 1700000000,
            "owned_by": "local",
        })
    return {"object": "list", "data": models}


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request, db: Session = Depends(get_db)):
    """OpenAI 호환 chat completions 엔드포인트.

    - model=ai-assistant → 기본 provider로 자동화 파이프라인 경유
    - model=ai-assistant:openai → OpenAI 강제 사용 + 자동화 파이프라인
    - model=ai-assistant:claude → Claude 강제 사용 + 자동화 파이프라인
    - model=ai-assistant:gemini → Gemini 강제 사용 + 자동화 파이프라인
    - model=<로컬 모델명> → 로컬 LLM 직접 포워딩
    - stream=true 지원
    """
    body = await request.json()
    model = body.get("model", _OPENAI_COMPAT_MODEL)
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # 마지막 user 메시지 추출
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    if not user_message:
        return _openai_chat_response("메시지가 비어 있습니다.", model=model)

    # ai-assistant 또는 ai-assistant:<provider> 패턴 매칭
    provider_hint: str | None = None
    is_assistant_model = False
    if model == _OPENAI_COMPAT_MODEL:
        is_assistant_model = True
    elif model.startswith(_OPENAI_COMPAT_MODEL_PREFIX):
        is_assistant_model = True
        provider_hint = model[len(_OPENAI_COMPAT_MODEL_PREFIX):]
        # claude → anthropic 정규화
        provider_hint = {"claude": "anthropic"}.get(provider_hint.lower(), provider_hint.lower())

    if not is_assistant_model:
        return _forward_to_local_llm(body, stream)

    # 자동화 파이프라인 실행
    reply = _openai_compat_process(user_message, db, provider_hint=provider_hint)

    if stream:
        chunks = _openai_stream_chunks(reply, model=model)

        async def generate():
            for chunk in chunks:
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return _openai_chat_response(reply, model=model)


def _openai_compat_process(user_message: str, db: Session, *, provider_hint: str | None = None) -> str:
    """OpenAI 호환 요청을 기존 _chat_impl 파이프라인으로 처리한다."""
    payload = ChatRequest(message=user_message, channel="webui")
    result = _chat_impl(payload, db, provider_hint=provider_hint)
    return result.reply


def _forward_to_local_llm(body: dict, stream: bool) -> Response | StreamingResponse:
    """로컬 LLM으로 OpenAI 요청을 그대로 프록시한다."""
    endpoint = f"{settings.local_llm.base_url.rstrip('/')}/chat/completions"
    try:
        if stream:
            # 스트리밍 프록시 — httpx sync stream을 async generator로 변환
            client = httpx.Client(timeout=settings.local_llm.timeout_seconds)
            upstream = client.send(
                client.build_request("POST", endpoint, json=body),
                stream=True,
            )
            upstream.raise_for_status()

            async def proxy_stream():
                try:
                    for line in upstream.iter_lines():
                        yield f"{line}\n"
                finally:
                    upstream.close()
                    client.close()

            return StreamingResponse(proxy_stream(), media_type="text/event-stream")
        else:
            with httpx.Client(timeout=settings.local_llm.timeout_seconds) as client:
                resp = client.post(endpoint, json=body)
                resp.raise_for_status()
            return Response(content=resp.content, media_type="application/json")
    except Exception as exc:
        logger.warning("Local LLM proxy failed: %s", exc)
        model = body.get("model", settings.local_llm.model)
        return Response(
            content=json.dumps(_openai_chat_response(
                f"로컬 LLM 연결 실패: {exc}", model=model,
            )),
            media_type="application/json",
        )


@app.post("/api/browser/read", response_model=BrowserReadResponse)
async def browser_read(payload: BrowserReadRequest, db: Session = Depends(get_db)) -> BrowserReadResponse:
    internal_user_id = _resolve_internal_user_id(db, payload.channel, payload.user_id)
    session = _resolve_channel_session(db, payload.channel, payload.session_id, internal_user_id, payload.url)

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


@app.post("/api/browser/screenshot")
async def browser_screenshot(payload: dict):
    """브라우저로 페이지 스크린샷을 찍어 base64 이미지를 반환한다."""
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    request_body = {
        "url": url,
        "timeoutMs": payload.get("timeoutMs", 15000),
        "fullPage": payload.get("fullPage", False),
        "viewportWidth": payload.get("viewportWidth", 1280),
        "viewportHeight": payload.get("viewportHeight", 720),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.browser_runner_base_url.rstrip('/')}/browse/screenshot",
                json=request_body,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"browser runner unavailable: {exc}") from exc

    return response.json()


@app.post("/api/browser/search")
async def browser_search(payload: dict):
    """브라우저 기반 Google 검색 결과를 반환한다."""
    query = payload.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    request_body = {
        "query": query,
        "maxResults": payload.get("maxResults", 5),
        "timeoutMs": payload.get("timeoutMs", 20000),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.browser_runner_base_url.rstrip('/')}/browse/search",
                json=request_body,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"browser runner unavailable: {exc}") from exc

    return response.json()


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
    if ticket.session_id:
        _record_assistant_message(db, ticket.session_id, "system", "승인 요청을 거절했습니다.", "rejected", ticket.action_type, ticket.id)
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


@app.post("/api/tasks/async")
def publish_async_task(body: dict):
    """비동기 작업을 Worker 큐에 발행한다."""
    from app.tasks import publish_task
    task_type = body.get("type", "chat")
    payload = body.get("payload", {})
    task_id = publish_task(task_type, payload)
    if task_id is None:
        raise HTTPException(status_code=503, detail="Worker 큐를 사용할 수 없습니다. Redis 연결을 확인하세요.")
    return {"task_id": task_id, "status": "queued"}


@app.get("/api/tasks/async/{task_id}")
def get_async_task_result(task_id: str):
    """Worker가 처리한 비동기 작업 결과를 조회한다."""
    from app.tasks import get_task_result
    result = get_task_result(task_id)
    if result is None:
        return {"task_id": task_id, "status": "pending"}
    return {"task_id": task_id, **result}


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
        structured_extraction=_build_structured_payload(
            pending_task.detail,
            session.channel,
            _session_history_context(db, session.id),
            _load_previous_extraction(db, session.id),
            last_candidates=_load_last_candidates(db, session.id),
        ),
        memory_context=_load_user_memory_context(db, session.user_id),
    )
    update_task_run_status(db, pending_task, status="completed", detail=pending_task.detail)
    reply = str(result["reply"])
    if ticket.action_type in {"gmail_draft", "gmail_send", "gmail_reply", "gmail_thread_reply"}:
        reply = format_gmail_action_reply(reply, session.channel)
    return reply, str(result["route"])


def _resolve_slack_session(
    db: Session,
    session_id: str | None,
    user_id: str | None,
    message: str,
) -> AssistantSession:
    return _resolve_channel_session(db, "slack", session_id, user_id, message)


def _process_slack_message(
    db: Session,
    message: str,
    user_id: str | None,
    session_id: str | None = None,
) -> tuple[str, str, str, str | None, str | None]:
    internal_user_id = _resolve_internal_user_id(db, "slack", user_id)
    approval_command = _match_approval_command(message)
    if approval_command is not None:
        return _handle_approval_command(approval_command, internal_user_id, db)

    session = _resolve_slack_session(db, session_id, internal_user_id, message)
    pending_command = _match_pending_ticket_command(db, session.id, message)
    if pending_command is not None:
        return _handle_approval_command(pending_command, internal_user_id, db)

    structured = _build_structured_payload(
        message,
        "slack",
        _session_history_context(db, session.id),
        _load_previous_extraction(db, session.id),
        last_candidates=_load_last_candidates(db, session.id),
    )
    memory_context = _load_user_memory_context(db, internal_user_id)
    _record_user_message(db, session, "slack", message, structured)
    result = process_message(
        message,
        "slack",
        session.id,
        internal_user_id,
        structured_extraction=structured,
        memory_context=memory_context,
    )
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
        reply = f"{result['reply']}\n티켓: {ticket.id}"
    else:
        create_task_run(db, session_id=session.id, task_type=str(result["route"]), detail=message)
        reply = str(result["reply"])

        _record_assistant_message(
            db,
            session.id,
            "slack",
            reply,
            str(result["route"]),
            action_type,
            approval_ticket_id,
            workflow_candidates=result.get("last_candidates"),
            workflow_state_data={"last_mail_result_context": result.get("mail_result_context")} if result.get("mail_result_context") else None,
        )

    return session.id, reply, str(result["route"]), approval_ticket_id, action_type


def _resolve_slack_event_session_id(db: Session, message: str, user_id: str | None) -> str:
    approval_command = _match_approval_command(message)
    if approval_command is not None:
        ticket = get_approval_ticket(db, approval_command[1])
        if ticket is not None and ticket.session_id:
            return ticket.session_id
        return "unknown"
    internal_user_id = _resolve_internal_user_id(db, "slack", user_id)
    session = _resolve_slack_session(db, None, internal_user_id, message)
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
