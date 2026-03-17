from pydantic import BaseModel
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict
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
    def resolved_admin_session_secret(self) -> str:
        return self.admin_session_secret or secrets.token_urlsafe(32)


settings = Settings()
