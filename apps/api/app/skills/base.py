"""스킬 메타데이터와 공통 인터페이스 정의."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field


class SkillDescriptor(BaseModel):
    """하나의 자동화 능력을 기술하는 메타데이터.

    레지스트리에 등록하면 의도 분류와 실행 라우팅에 자동으로 참여한다.
    """

    skill_id: str
    name: str
    description: str
    domain: str
    action: str
    trigger_keywords: list[str] = Field(default_factory=list)
    intent_examples: list[str] = Field(default_factory=list)
    disambiguation_hints: list[str] = Field(default_factory=list)
    input_schema: dict | None = None
    output_schema: dict | None = None
    executor_type: Literal["n8n", "macos", "browser", "mcp", "local_function", "api"] = "n8n"
    executor_ref: str = ""
    approval_required: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    allowed_channels: list[str] = Field(default_factory=lambda: ["web", "slack", "kakao"])
    enabled: bool = True


class BaseSkill(ABC):
    """모든 스킬이 구현하는 공통 인터페이스."""

    @abstractmethod
    def descriptor(self) -> SkillDescriptor:
        """스킬 메타데이터를 반환한다."""
        ...

    @abstractmethod
    async def extract(self, message: str, context: dict) -> BaseModel | None:
        """사용자 메시지에서 실행에 필요한 파라미터를 추출한다."""
        ...

    @abstractmethod
    async def validate(self, params: BaseModel) -> list[str]:
        """추출된 파라미터의 유효성을 검증하고 누락 필드 목록을 반환한다."""
        ...

    @abstractmethod
    async def execute(self, params: BaseModel, context: dict) -> dict:
        """실제 작업을 실행하고 결과를 반환한다."""
        ...
