from pydantic import BaseModel
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class LocalLLMSettings(BaseModel):
    provider: str = Field(default="ollama")
    base_url: str = Field(default="http://localhost:11434/v1")
    model: str = Field(default="qwen3:8b")


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
    browser_runner_base_url: str = Field(default="http://browser-runner:8080", alias="BROWSER_RUNNER_BASE_URL")
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    slack_app_token: str = Field(default="", alias="SLACK_APP_TOKEN")
    slack_signing_secret: str = Field(default="", alias="SLACK_SIGNING_SECRET")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def local_llm(self) -> LocalLLMSettings:
        return LocalLLMSettings(
            provider=self.local_llm_provider,
            base_url=self.local_llm_base_url,
            model=self.local_llm_model,
        )


settings = Settings()
