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
    execute_calendar_summary,
    execute_calendar_write,
    execute_chat,
    execute_gmail_compose,
    execute_gmail_detail,
    execute_gmail_reply,
    execute_gmail_summary,
    execute_macos_darkmode,
    execute_macos_finder,
    execute_macos_note,
    execute_macos_reminder,
    execute_macos_volume_get,
    execute_macos_volume_set,
    execute_mcp_tool,
    execute_web_search,
    validate,
)
from app.graph.state import AssistantState


# ---------------------------------------------------------------------------
# 라우팅 함수 (조건부 엣지)
# ---------------------------------------------------------------------------

def _route_after_validate(state: AssistantState) -> str:
    """validate 이후 intent에 따라 다음 노드를 결정한다."""
    if state.get("route") == "validation_error":
        return "end_validation_error"

    intent = state["intent"]
    if intent == "calendar_summary":
        return "execute_calendar_summary"
    if intent in {"calendar_create", "calendar_update", "calendar_delete"}:
        return "check_approval_calendar"
    if intent in {"gmail_draft", "gmail_send"}:
        return "check_approval_gmail_compose"
    if intent in {"gmail_reply", "gmail_thread_reply"}:
        return "check_approval_gmail_reply"
    if intent in {"gmail_summary", "gmail_list"}:
        return "execute_gmail_summary"
    if intent == "gmail_detail":
        return "execute_gmail_detail"
    if intent == "macos_note_create":
        return "check_approval_macos_note"
    if intent == "macos_reminder_create":
        return "check_approval_macos_reminder"
    if intent == "macos_volume_get":
        return "execute_macos_volume_get"
    if intent == "macos_volume_set":
        return "check_approval_macos_volume_set"
    if intent == "macos_darkmode_toggle":
        return "check_approval_macos_darkmode"
    if intent == "macos_finder_open":
        return "execute_macos_finder"
    if intent == "web_search":
        return "execute_web_search"
    # MCP 도구 intent (mcp_ 접두사)
    if intent.startswith("mcp_"):
        return "execute_mcp_tool"
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
    graph.add_node("check_approval_calendar", check_approval)
    graph.add_node("check_approval_gmail_compose", check_approval)
    graph.add_node("check_approval_gmail_reply", check_approval)
    graph.add_node("check_approval_macos_note", check_approval)
    graph.add_node("check_approval_macos_reminder", check_approval)
    graph.add_node("check_approval_macos_volume_set", check_approval)
    graph.add_node("check_approval_macos_darkmode", check_approval)
    graph.add_node("execute_calendar_summary", execute_calendar_summary)
    graph.add_node("execute_calendar_write", execute_calendar_write)
    graph.add_node("execute_gmail_compose", execute_gmail_compose)
    graph.add_node("execute_gmail_detail", execute_gmail_detail)
    graph.add_node("execute_gmail_reply", execute_gmail_reply)
    graph.add_node("execute_gmail_summary", execute_gmail_summary)
    graph.add_node("execute_macos_note", execute_macos_note)
    graph.add_node("execute_macos_reminder", execute_macos_reminder)
    graph.add_node("execute_macos_volume_get", execute_macos_volume_get)
    graph.add_node("execute_macos_volume_set", execute_macos_volume_set)
    graph.add_node("execute_macos_darkmode", execute_macos_darkmode)
    graph.add_node("execute_macos_finder", execute_macos_finder)
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
            "execute_calendar_summary": "execute_calendar_summary",
            "check_approval_calendar": "check_approval_calendar",
            "check_approval_gmail_compose": "check_approval_gmail_compose",
            "check_approval_gmail_reply": "check_approval_gmail_reply",
            "execute_gmail_summary": "execute_gmail_summary",
            "execute_gmail_detail": "execute_gmail_detail",
            "check_approval_macos_note": "check_approval_macos_note",
            "check_approval_macos_reminder": "check_approval_macos_reminder",
            "execute_macos_volume_get": "execute_macos_volume_get",
            "check_approval_macos_volume_set": "check_approval_macos_volume_set",
            "check_approval_macos_darkmode": "check_approval_macos_darkmode",
            "execute_macos_finder": "execute_macos_finder",
            "execute_web_search": "execute_web_search",
            "execute_mcp_tool": "execute_mcp_tool",
            "execute_chat": "execute_chat",
        },
    )

    # 승인 확인 → 조건부 실행
    graph.add_conditional_edges(
        "check_approval_calendar",
        _route_after_approval("execute_calendar_write"),
        {"end_approval": END, "execute_calendar_write": "execute_calendar_write"},
    )
    graph.add_conditional_edges(
        "check_approval_gmail_compose",
        _route_after_approval("execute_gmail_compose"),
        {"end_approval": END, "execute_gmail_compose": "execute_gmail_compose"},
    )
    graph.add_conditional_edges(
        "check_approval_gmail_reply",
        _route_after_approval("execute_gmail_reply"),
        {"end_approval": END, "execute_gmail_reply": "execute_gmail_reply"},
    )
    graph.add_conditional_edges(
        "check_approval_macos_note",
        _route_after_approval("execute_macos_note"),
        {"end_approval": END, "execute_macos_note": "execute_macos_note"},
    )
    graph.add_conditional_edges(
        "check_approval_macos_reminder",
        _route_after_approval("execute_macos_reminder"),
        {"end_approval": END, "execute_macos_reminder": "execute_macos_reminder"},
    )
    graph.add_conditional_edges(
        "check_approval_macos_volume_set",
        _route_after_approval("execute_macos_volume_set"),
        {"end_approval": END, "execute_macos_volume_set": "execute_macos_volume_set"},
    )
    graph.add_conditional_edges(
        "check_approval_macos_darkmode",
        _route_after_approval("execute_macos_darkmode"),
        {"end_approval": END, "execute_macos_darkmode": "execute_macos_darkmode"},
    )

    # 실행 노드 → 종료
    graph.add_edge("execute_calendar_summary", END)
    graph.add_edge("execute_calendar_write", END)
    graph.add_edge("execute_gmail_compose", END)
    graph.add_edge("execute_gmail_detail", END)
    graph.add_edge("execute_gmail_reply", END)
    graph.add_edge("execute_gmail_summary", END)
    graph.add_edge("execute_macos_note", END)
    graph.add_edge("execute_macos_reminder", END)
    graph.add_edge("execute_macos_volume_get", END)
    graph.add_edge("execute_macos_volume_set", END)
    graph.add_edge("execute_macos_darkmode", END)
    graph.add_edge("execute_macos_finder", END)
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
