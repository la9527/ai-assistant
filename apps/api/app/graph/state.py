"""워크플로 상태 정의."""

from __future__ import annotations

from typing import Any, TypedDict

from app.schemas import StructuredExtraction


class AssistantState(TypedDict, total=False):
    """LangGraph 워크플로 전체에서 전달되는 상태."""

    # --- 입력 ---
    message: str
    channel: str
    session_id: str
    user_id: str | None
    approval_granted: bool
    intent_override: str | None
    memory_context: list[dict[str, str]] | None
    structured_extraction: StructuredExtraction | None  # 사전 구축된 extraction (참조 컨텍스트 적용 완료)

    # --- 중간 산출물 ---
    extraction: StructuredExtraction | None
    intent: str
    parsed_params: dict[str, str] | None

    # --- 출력 ---
    reply: str
    route: str
    action_type: str | None
