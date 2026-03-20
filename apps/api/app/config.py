from pydantic import BaseModel
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict
import json
import secrets


class LocalLLMSettings(BaseModel):
    provider: str = Field(default="ollama")
    base_url: str = Field(default="http://localhost:11434/v1")
    model: str = Field(default="qwen3:8b")
    timeout_seconds: float = Field(default=90.0)
    prewarm_enabled: bool = Field(default=True)
    structured_extraction_base_url: str = Field(default="http://localhost:11434/v1")
    structured_extraction_model: str = Field(default="qwen3:8b")
    structured_extraction_enabled: bool = Field(default=True)
    structured_extraction_timeout_seconds: float = Field(default=25.0)
    structured_extraction_targets: tuple[str, ...] = ("calendar_delete", "gmail_reply", "gmail_thread_reply")


class ExternalLLMSettings(BaseModel):
    """외부 LLM 설정.

    provider 별 기본값:
      - openai : base_url=https://api.openai.com/v1, model=gpt-4o-mini
      - anthropic: base_url=https://api.anthropic.com, model=claude-sonnet-4-20250514
      - gemini  : base_url=https://generativelanguage.googleapis.com, model=gemini-2.5-flash
    """

    enabled: bool = Field(default=False)
    provider: str = Field(default="openai")
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: str = Field(default="")
    model: str = Field(default="gpt-4o-mini")
    timeout_seconds: float = Field(default=60.0)
    fallback_only: bool = Field(default=True)
    structured_extraction_enabled: bool = Field(default=False)
    structured_extraction_model: str = Field(default="")


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    database_url: str = Field(default="postgresql://app:app@postgres:5432/assistant", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    n8n_base_url: str = Field(default="http://n8n:5678", alias="N8N_BASE_URL")
    n8n_webhook_path: str = Field(default="", alias="N8N_WEBHOOK_PATH")
    n8n_calendar_create_webhook_path: str = Field(default="", alias="N8N_CALENDAR_CREATE_WEBHOOK_PATH")
    n8n_calendar_update_webhook_path: str = Field(default="", alias="N8N_CALENDAR_UPDATE_WEBHOOK_PATH")
    n8n_calendar_delete_webhook_path: str = Field(
        default="webhook/assistant-calendar-delete",
        alias="N8N_CALENDAR_DELETE_WEBHOOK_PATH",
    )
    n8n_gmail_webhook_path: str = Field(default="", alias="N8N_GMAIL_WEBHOOK_PATH")
    n8n_gmail_draft_webhook_path: str = Field(
        default="webhook/assistant-gmail-draft",
        alias="N8N_GMAIL_DRAFT_WEBHOOK_PATH",
    )
    n8n_gmail_send_webhook_path: str = Field(
        default="webhook/assistant-gmail-send",
        alias="N8N_GMAIL_SEND_WEBHOOK_PATH",
    )
    n8n_gmail_reply_webhook_path: str = Field(
        default="webhook/assistant-gmail-reply",
        alias="N8N_GMAIL_REPLY_WEBHOOK_PATH",
    )
    n8n_gmail_detail_webhook_path: str = Field(
        default="webhook/assistant-gmail-detail",
        alias="N8N_GMAIL_DETAIL_WEBHOOK_PATH",
    )
    n8n_webhook_token: str = Field(default="", alias="N8N_WEBHOOK_TOKEN")
    local_llm_provider: str = Field(default="ollama", alias="LOCAL_LLM_PROVIDER")
    local_llm_base_url: str = Field(default="http://localhost:11434/v1", alias="LOCAL_LLM_BASE_URL")
    local_llm_model: str = Field(default="qwen3:8b", alias="LOCAL_LLM_MODEL")
    local_llm_timeout_seconds: float = Field(default=90.0, alias="LOCAL_LLM_TIMEOUT_SECONDS")
    local_llm_prewarm_enabled: bool = Field(default=True, alias="LOCAL_LLM_PREWARM_ENABLED")
    local_llm_structured_extraction_enabled: bool = Field(default=True, alias="LOCAL_LLM_STRUCTURED_EXTRACTION_ENABLED")
    local_llm_structured_extraction_base_url: str = Field(
        default="",
        alias="LOCAL_LLM_STRUCTURED_EXTRACTION_BASE_URL",
    )
    local_llm_structured_extraction_model: str = Field(default="", alias="LOCAL_LLM_STRUCTURED_EXTRACTION_MODEL")
    local_llm_structured_extraction_timeout_seconds: float = Field(
        default=25.0,
        alias="LOCAL_LLM_STRUCTURED_EXTRACTION_TIMEOUT_SECONDS",
    )
    local_llm_structured_extraction_targets_raw: str = Field(
        default="calendar_delete,gmail_reply,gmail_thread_reply",
        alias="LOCAL_LLM_STRUCTURED_EXTRACTION_TARGETS",
    )
    browser_runner_base_url: str = Field(default="http://browser-runner:8080", alias="BROWSER_RUNNER_BASE_URL")
    macos_automation_base_url: str = Field(default="http://host.docker.internal:8091", alias="MACOS_AUTOMATION_BASE_URL")
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    slack_app_token: str = Field(default="", alias="SLACK_APP_TOKEN")
    slack_signing_secret: str = Field(default="", alias="SLACK_SIGNING_SECRET")
    slack_auto_response_channels_raw: str = Field(default="ai비서", alias="SLACK_AUTO_RESPONSE_CHANNELS")
    admin_username: str = Field(default="", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    admin_session_secret: str = Field(default="", alias="ADMIN_SESSION_SECRET")
    admin_session_ttl_seconds: int = Field(default=43200, alias="ADMIN_SESSION_TTL_SECONDS")
    external_llm_enabled: bool = Field(default=False, alias="EXTERNAL_LLM_ENABLED")
    external_llm_provider: str = Field(default="openai", alias="EXTERNAL_LLM_PROVIDER")
    external_llm_base_url: str = Field(default="https://api.openai.com/v1", alias="EXTERNAL_LLM_BASE_URL")
    external_llm_api_key: str = Field(default="", alias="EXTERNAL_LLM_API_KEY")
    external_llm_model: str = Field(default="gpt-4o-mini", alias="EXTERNAL_LLM_MODEL")
    external_llm_timeout_seconds: float = Field(default=60.0, alias="EXTERNAL_LLM_TIMEOUT_SECONDS")
    external_llm_fallback_only: bool = Field(default=True, alias="EXTERNAL_LLM_FALLBACK_ONLY")
    external_llm_structured_extraction_enabled: bool = Field(
        default=False, alias="EXTERNAL_LLM_STRUCTURED_EXTRACTION_ENABLED"
    )
    external_llm_structured_extraction_model: str = Field(
        default="", alias="EXTERNAL_LLM_STRUCTURED_EXTRACTION_MODEL"
    )
    # provider별 개별 API 키/모델 설정
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514", alias="ANTHROPIC_MODEL")
    anthropic_base_url: str = Field(default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com", alias="GEMINI_BASE_URL")
    web_search_enabled: bool = Field(default=False, alias="WEB_SEARCH_ENABLED")
    web_search_provider: str = Field(default="tavily", alias="WEB_SEARCH_PROVIDER")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    web_search_max_results: int = Field(default=5, alias="WEB_SEARCH_MAX_RESULTS")
    api_key: str = Field(default="", alias="API_KEY")
    rate_limit_chat: str = Field(default="30/minute", alias="RATE_LIMIT_CHAT")
    rate_limit_default: str = Field(default="60/minute", alias="RATE_LIMIT_DEFAULT")
    mcp_servers_json: str = Field(default="", alias="MCP_SERVERS")
    calendar_timezone: str = Field(default="Asia/Seoul", alias="CALENDAR_TIMEZONE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def local_llm(self) -> LocalLLMSettings:
        return LocalLLMSettings(
            provider=self.local_llm_provider,
            base_url=self.local_llm_base_url,
            model=self.local_llm_model,
            timeout_seconds=self.local_llm_timeout_seconds,
            prewarm_enabled=self.local_llm_prewarm_enabled,
            structured_extraction_base_url=self.local_llm_structured_extraction_base_url or self.local_llm_base_url,
            structured_extraction_model=self.local_llm_structured_extraction_model or self.local_llm_model,
            structured_extraction_enabled=self.local_llm_structured_extraction_enabled,
            structured_extraction_timeout_seconds=self.local_llm_structured_extraction_timeout_seconds,
            structured_extraction_targets=tuple(
                item.strip() for item in self.local_llm_structured_extraction_targets_raw.split(",") if item.strip()
            ),
        )

    @property
    def external_llm(self) -> ExternalLLMSettings:
        return ExternalLLMSettings(
            enabled=self.external_llm_enabled and bool(self.external_llm_api_key),
            provider=self.external_llm_provider,
            base_url=self.external_llm_base_url,
            api_key=self.external_llm_api_key,
            model=self.external_llm_model,
            timeout_seconds=self.external_llm_timeout_seconds,
            fallback_only=self.external_llm_fallback_only,
            structured_extraction_enabled=self.external_llm_structured_extraction_enabled,
            structured_extraction_model=(
                self.external_llm_structured_extraction_model or self.external_llm_model
            ),
        )

    # ----- provider별 개별 ExternalLLMSettings 구성 -----

    _PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
        "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
        "anthropic": {"base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-20250514"},
        "gemini": {"base_url": "https://generativelanguage.googleapis.com", "model": "gemini-2.5-flash"},
    }

    def resolve_external_llm(self, provider: str | None = None) -> ExternalLLMSettings:
        """지정된 provider의 ExternalLLMSettings를 구성한다.

        provider가 None이면 기본 external_llm 속성을 반환한다.
        개별 provider 키가 설정되어 있으면 해당 키를 사용하고,
        없으면 기본 EXTERNAL_LLM_* 설정을 fallback으로 사용한다.
        """
        if provider is None:
            return self.external_llm
        prov = provider.lower()
        key_map = {
            "openai": (self.openai_api_key, self.openai_model, self.openai_base_url),
            "anthropic": (self.anthropic_api_key, self.anthropic_model, self.anthropic_base_url),
            "gemini": (self.gemini_api_key, self.gemini_model, self.gemini_base_url),
        }
        if prov not in key_map:
            return self.external_llm
        api_key, model, base_url = key_map[prov]
        # 개별 키가 없으면 기본 외부 LLM 설정 fallback
        if not api_key:
            api_key = self.external_llm_api_key
            model = model or self.external_llm_model
            base_url = base_url or self.external_llm_base_url
        return ExternalLLMSettings(
            enabled=bool(api_key),
            provider=prov,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=self.external_llm_timeout_seconds,
            fallback_only=False,
            structured_extraction_enabled=self.external_llm_structured_extraction_enabled,
            structured_extraction_model=(
                self.external_llm_structured_extraction_model or model
            ),
        )

    def available_external_providers(self) -> list[dict[str, str]]:
        """API 키가 설정된 외부 LLM provider 목록을 반환한다."""
        providers: list[dict[str, str]] = []
        key_map = {
            "openai": (self.openai_api_key, self.openai_model),
            "anthropic": (self.anthropic_api_key, self.anthropic_model),
            "gemini": (self.gemini_api_key, self.gemini_model),
        }
        for prov, (api_key, model) in key_map.items():
            # 개별 키가 있거나, 기본 외부 LLM이 해당 provider이면 활성
            effective_key = api_key or (
                self.external_llm_api_key
                if self.external_llm_provider.lower() == prov and self.external_llm_enabled
                else ""
            )
            if effective_key:
                providers.append({"provider": prov, "model": model})
        return providers

    @property
    def slack_auto_response_channels(self) -> set[str]:
        return {
            item.strip().lstrip("#").lower()
            for item in self.slack_auto_response_channels_raw.split(",")
            if item.strip()
        }

    @property
    def admin_auth_enabled(self) -> bool:
        return bool(self.admin_username.strip() and self.admin_password)

    @property
    def web_search_available(self) -> bool:
        return self.web_search_enabled and bool(self.tavily_api_key)

    @property
    def resolved_admin_session_secret(self) -> str:
        return self.admin_session_secret or secrets.token_urlsafe(32)

    @property
    def mcp_servers(self) -> list[dict]:
        """MCP_SERVERS 환경변수에서 서버 설정 목록을 파싱한다.

        형식: JSON 배열 예시:
        [{"name": "filesystem", "transport": "sse", "url": "http://localhost:3001/sse"}]
        """
        if not self.mcp_servers_json.strip():
            return []
        try:
            parsed = json.loads(self.mcp_servers_json)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return []


settings = Settings()
