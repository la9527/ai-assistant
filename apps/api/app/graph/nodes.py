"""LangGraph 노드 함수 — 기존 automation.py 로직을 노드 단위로 분리.

모든 도메인별 실행(Gmail, Calendar, macOS 등)은 skill registry 기반
execute_skill 노드를 통해 수행된다. 개별 execute_* 노드는 사용하지 않는다.
"""

from __future__ import annotations

from app.automation import (
    _build_skill_approval_reply,
    _build_skill_validation_error,
    _execute_registered_skill_runtime,
    _validate_registered_skill,
    extract_structured_request,
)
from app.config import settings
from app.graph.state import AssistantState
from app.llm import generate_external_reply, generate_local_reply
from app.skills.registry import get_skill_runtime


def _generate_reply_with_external_fallback(
    message: str,
    channel: str,
    memory_context: list[dict[str, str]] | None = None,
    *,
    provider_hint: str | None = None,
) -> tuple[str, str]:
    """외부 LLM이 primary이면 외부 우선, 아니면 로컬 우선으로 응답을 생성한다."""
    # provider_hint가 있으면 해당 외부 LLM을 사용
    if provider_hint:
        reply, route = generate_external_reply(message, channel, memory_context, provider_hint=provider_hint)
        if route == "external_llm":
            return reply, route
        return generate_local_reply(message, channel, memory_context)
    ext = settings.external_llm
    if ext.enabled and not ext.fallback_only:
        reply, route = generate_external_reply(message, channel, memory_context)
        if route == "external_llm":
            return reply, route
    return generate_local_reply(message, channel, memory_context)



# ---------------------------------------------------------------------------
# 1. classify — 의도 분류 + 구조화 추출
# ---------------------------------------------------------------------------

def classify(state: AssistantState) -> dict:
    pre_built = state.get("structured_extraction")
    if pre_built is not None:
        extraction = pre_built
    else:
        extraction = extract_structured_request(state["message"], state.get("channel"))
    intent = state.get("intent_override") or extraction.intent

    # 이전 gmail_summary/gmail_list 결과에서 특정 항목을 참조하는 경우 → chat으로 전환
    if intent in {"gmail_summary", "gmail_list"} and extraction.metadata.get("candidate_selected"):
        intent = "chat"

    return {"extraction": extraction, "intent": intent}


# ---------------------------------------------------------------------------
# 2. validate — 파라미터 파싱 + 검증
# ---------------------------------------------------------------------------

def validate(state: AssistantState) -> dict:
    intent = state["intent"]
    extraction = state.get("extraction")
    if extraction is not None:
        missing_fields = _validate_registered_skill(extraction, intent)
        if missing_fields is not None and missing_fields:
            return {
                "parsed_params": None,
                "reply": _build_skill_validation_error(intent, extraction),
                "route": "validation_error",
                "action_type": intent,
            }
    return {"parsed_params": None}


# ---------------------------------------------------------------------------
# 3. check_approval — 승인 필요 여부 확인
# ---------------------------------------------------------------------------

def check_approval(state: AssistantState) -> dict:
    intent = state["intent"]
    runtime = get_skill_runtime(intent)
    if runtime is None or not runtime.descriptor().approval_required:
        return {}
    if state.get("approval_granted"):
        return {}
    return {
        "reply": _build_skill_approval_reply(intent, runtime.descriptor().name),
        "route": "approval_required",
        "action_type": intent,
    }


def execute_skill(state: AssistantState) -> dict:
    extraction = state.get("extraction")
    if extraction is None:
        return {
            "reply": "실행할 스킬 정보를 찾지 못했습니다.",
            "route": "validation_error",
            "action_type": state.get("intent"),
        }
    result = _execute_registered_skill_runtime(
        extraction=extraction,
        message=state["message"],
        channel=state.get("channel", ""),
        session_id=state.get("session_id", ""),
        user_id=state.get("user_id"),
        memory_context=state.get("memory_context"),
        skill_id=state.get("intent"),
    )
    return result or {
        "reply": "실행 가능한 스킬을 찾지 못했습니다.",
        "route": "validation_error",
        "action_type": state.get("intent"),
    }


# ---------------------------------------------------------------------------
# 4. execute — 실행 노드들
# ---------------------------------------------------------------------------


def execute_chat(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    memory_context = state.get("memory_context")
    provider_hint = state.get("provider_hint")
    extraction = state.get("extraction")

    # 이전 대화 후보 항목 참조 시 해당 정보를 LLM 컨텍스트에 주입
    enriched_message = message
    if extraction and extraction.metadata.get("candidate_selected"):
        candidate_data = extraction.metadata.get("candidate_data") or {}
        if candidate_data:
            context_parts = ["다음은 이전 대화에서 사용자가 참조한 항목 정보이다:"]
            if candidate_data.get("sender"):
                context_parts.append(f"- 보낸사람: {candidate_data['sender']}")
            if candidate_data.get("label"):
                context_parts.append(f"- 제목: {candidate_data['label']}")
            if candidate_data.get("snippet"):
                context_parts.append(f"- 미리보기: {candidate_data['snippet']}")
            if candidate_data.get("date"):
                context_parts.append(f"- 날짜: {candidate_data['date']}")
            if candidate_data.get("raw"):
                context_parts.append(f"- 원본: {candidate_data['raw']}")
            context_parts.append(f"\n사용자 질문: {message}")
            enriched_message = "\n".join(context_parts)

    reply, route = _generate_reply_with_external_fallback(enriched_message, channel, memory_context, provider_hint=provider_hint)
    return {"reply": reply, "route": route, "action_type": None}


def execute_mcp_tool(state: AssistantState) -> dict:
    """MCP 도구를 호출하는 실행 노드."""
    from app.mcp.client import call_mcp_tool_sync
    from app.skills.registry import get_skill_by_id

    intent = state["intent"]
    parsed = state.get("parsed_params") or {}

    skill = get_skill_by_id(intent)
    if skill is None or skill.executor_type != "mcp":
        return {
            "reply": f"MCP 도구를 찾을 수 없습니다: {intent}",
            "route": "mcp_error",
            "action_type": intent,
        }

    # executor_ref: "server_name/tool_name"
    parts = skill.executor_ref.split("/", 1)
    tool_name = parts[1] if len(parts) > 1 else skill.executor_ref

    try:
        reply = call_mcp_tool_sync(tool_name, parsed if parsed else None)
        return {"reply": reply, "route": "mcp", "action_type": intent}
    except Exception as exc:
        return {
            "reply": f"MCP 도구 실행 실패: {exc}",
            "route": "mcp_error",
            "action_type": intent,
        }


def execute_web_search(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    memory_context = state.get("memory_context")

    from app.search import run_web_search, format_search_results_for_llm

    search_result = run_web_search(message)
    if search_result.get("error"):
        reply, route = generate_local_reply(message, channel, memory_context)
        return {"reply": reply, "route": route, "action_type": None}

    context_text = format_search_results_for_llm(search_result)
    search_memory = [{"category": "search_context", "content": context_text, "source": "web_search"}]
    combined_memory = (memory_context or []) + search_memory
    reply, route = generate_local_reply(
        f"다음 검색 결과를 바탕으로 사용자 질문에 답변해줘.\n\n{context_text}\n\n사용자 질문: {message}",
        channel,
        combined_memory,
    )
    return {"reply": reply, "route": "web_search", "action_type": "web_search"}
