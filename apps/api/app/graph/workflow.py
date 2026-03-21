"""LangGraph StateGraph 워크플로 정의.

그래프 구조:
    classify → validate → (route_intent)
        ├─ validation_error → END
        ├─ calendar_summary  → execute_calendar_summary  → END
        ├─ calendar_write    → check_approval → (approved?)
        │                        ├─ yes → execute_calendar_write → END
        │                        └─ no  → END (approval_required)
        ├─ gmail_compose     → check_approval → execute_gmail_compose → END
        ├─ gmail_reply       → check_approval → execute_gmail_reply   → END
        ├─ gmail_summary     → execute_gmail_summary    → END
        ├─ gmail_detail      → execute_gmail_detail     → END
        ├─ macos_note        → check_approval → execute_macos_note    → END
        ├─ macos_reminder    → check_approval → execute_macos_reminder → END
        ├─ macos_volume_get  → execute_macos_volume_get → END
        ├─ macos_volume_set  → check_approval → execute_macos_volume_set → END
        ├─ macos_darkmode    → check_approval → execute_macos_darkmode   → END
        ├─ macos_finder      → execute_macos_finder     → END
        ├─ mcp_*             → execute_mcp_tool         → END
        └─ chat              → execute_chat             → END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    check_approval,
    classify,
    execute_chat,
    execute_mcp_tool,
    execute_skill,
    execute_web_search,
    validate,
)
from app.graph.state import AssistantState
from app.skills.registry import ensure_initialized as _ensure_skills
from app.skills.registry import get_skill_runtime


# ---------------------------------------------------------------------------
# 라우팅 함수 (조건부 엣지)
# ---------------------------------------------------------------------------

def _route_after_validate(state: AssistantState) -> str:
    """validate 이후 intent에 따라 다음 노드를 결정한다."""
    if state.get("route") == "validation_error":
        return "end_validation_error"

    intent = state["intent"]
    # MCP 도구 intent (mcp_ 접두사)
    if intent.startswith("mcp_"):
        return "execute_mcp_tool"
    if intent == "chat":
        return "execute_chat"
    _ensure_skills()
    runtime = get_skill_runtime(intent)
    if runtime is not None:
        if runtime.descriptor().approval_required:
            return "check_approval_skill"
        return "execute_skill"
    if intent == "web_search":
        return "execute_web_search"
    return "execute_chat"


def _route_after_approval(execute_node: str):
    """승인 확인 후 승인 필요 시 종료, 승인 완료 시 실행 노드로 진행."""
    def _router(state: AssistantState) -> str:
        if state.get("route") == "approval_required":
            return "end_approval"
        return execute_node
    return _router


# ---------------------------------------------------------------------------
# 그래프 빌드
# ---------------------------------------------------------------------------

def build_assistant_graph() -> StateGraph:
    graph = StateGraph(AssistantState)

    # 노드 등록
    graph.add_node("classify", classify)
    graph.add_node("validate", validate)
    graph.add_node("check_approval_skill", check_approval)
    graph.add_node("execute_skill", execute_skill)
    graph.add_node("execute_web_search", execute_web_search)
    graph.add_node("execute_mcp_tool", execute_mcp_tool)
    graph.add_node("execute_chat", execute_chat)

    # 엣지
    graph.set_entry_point("classify")
    graph.add_edge("classify", "validate")

    # validate → 조건부 라우팅
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "end_validation_error": END,
            "check_approval_skill": "check_approval_skill",
            "execute_skill": "execute_skill",
            "execute_web_search": "execute_web_search",
            "execute_mcp_tool": "execute_mcp_tool",
            "execute_chat": "execute_chat",
        },
    )

    # 승인 확인 → 조건부 실행
    graph.add_conditional_edges(
        "check_approval_skill",
        _route_after_approval("execute_skill"),
        {"end_approval": END, "execute_skill": "execute_skill"},
    )

    # 실행 노드 → 종료
    graph.add_edge("execute_skill", END)
    graph.add_edge("execute_web_search", END)
    graph.add_edge("execute_mcp_tool", END)
    graph.add_edge("execute_chat", END)

    return graph


# 컴파일된 워크플로 (싱글턴)
_compiled = None


def get_workflow():
    """컴파일된 워크플로를 반환한다. 최초 호출 시 빌드."""
    global _compiled
    if _compiled is None:
        _compiled = build_assistant_graph().compile()
    return _compiled


def run_workflow(
    message: str,
    channel: str,
    session_id: str,
    user_id: str | None = None,
    intent_override: str | None = None,
    approval_granted: bool = False,
    memory_context: list[dict[str, str]] | None = None,
    structured_extraction: "StructuredExtraction | None" = None,
    provider_hint: str | None = None,
) -> dict[str, str | None]:
    """process_message 대체 진입점 — LangGraph 워크플로를 실행한다."""
    from app.schemas import StructuredExtraction as _SE  # noqa: F811
    workflow = get_workflow()
    initial_state: AssistantState = {
        "message": message,
        "channel": channel,
        "session_id": session_id,
        "user_id": user_id,
        "approval_granted": approval_granted,
        "intent_override": intent_override,
        "memory_context": memory_context,
        "structured_extraction": structured_extraction,
        "provider_hint": provider_hint,
    }
    result = workflow.invoke(initial_state)
    return {
        "reply": result.get("reply", "처리할 수 없는 요청입니다."),
        "route": result.get("route", "unknown"),
        "action_type": result.get("action_type"),
        "last_candidates": result.get("last_candidates"),
        "mail_result_context": result.get("mail_result_context"),
    }
