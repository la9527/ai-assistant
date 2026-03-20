"""LangGraph 노드 함수 — 기존 automation.py 로직을 노드 단위로 분리."""

from __future__ import annotations

from app.automation import (
    ACTION_LABELS,
    _calendar_payload_to_request,
    _mail_payload_to_compose_request,
    _mail_payload_to_detail_request,
    _mail_payload_to_reply_request,
    extract_structured_request,
    parse_calendar_request,
    parse_gmail_compose_request,
    parse_gmail_detail_request,
    parse_gmail_reply_request,
    parse_macos_finder_open_request,
    parse_macos_note_request,
    parse_macos_reminder_request,
    parse_macos_volume_set_request,
    run_macos_automation,
    run_macos_get,
    run_n8n_automation,
    run_n8n_automation_raw,
)
from app.config import settings
from app.graph.state import AssistantState
from app.llm import format_gmail_summary, generate_external_reply, generate_local_reply


def _build_mail_result_context(raw_body: dict, items: list[dict], *, mode: str, selected_item: dict | None = None) -> dict:
    return {
        "mode": mode,
        "query": raw_body.get("query") or raw_body.get("searchQuery") or "",
        "items": items,
        "hasMore": bool(raw_body.get("hasMore")),
        "nextCursor": raw_body.get("nextCursor"),
        "groupByDate": bool(raw_body.get("groupByDate")),
        "selectedMessageId": (selected_item or {}).get("messageId") or (selected_item or {}).get("message_id"),
        "selectedThreadId": (selected_item or {}).get("threadId") or (selected_item or {}).get("thread_id"),
    }


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
    message = state["message"]

    if intent in {"calendar_create", "calendar_update", "calendar_delete"}:
        parsed = (
            _calendar_payload_to_request(extraction.calendar, intent)
            if extraction and extraction.calendar
            else parse_calendar_request(message, intent)
        )
        if parsed is None:
            example = (
                "내일 오후 3시에 치과 일정 추가해줘"
                if intent == "calendar_create"
                else "내일 오후 4시 치과 일정 변경해줘"
                if intent == "calendar_update"
                else "오늘 06:00-07:00 피자 시키기 일정 삭제해줘"
            )
            guidance = "삭제할 일정의 제목이나 시간을 더 구체적으로 알려주세요. " if intent == "calendar_delete" else ""
            return {
                "parsed_params": None,
                "reply": f"일정 요청을 이해하지 못했습니다. {guidance}예: {example}",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent in {"gmail_draft", "gmail_send"}:
        parsed = (
            _mail_payload_to_compose_request(extraction.mail, intent)
            if extraction and extraction.mail
            else parse_gmail_compose_request(message, intent)
        )
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "메일 작성 요청을 이해하지 못했습니다. 예: test@example.com로 제목 주간 보고, 내용 오늘 작업 완료 메일 초안 작성해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent in {"gmail_reply", "gmail_thread_reply"}:
        parsed = (
            _mail_payload_to_reply_request(extraction.mail, intent)
            if extraction and extraction.mail
            else parse_gmail_reply_request(message, intent)
        )
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "메일 회신 요청을 이해하지 못했습니다. 예: 제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent == "gmail_detail":
        parsed = (
            _mail_payload_to_detail_request(extraction.mail)
            if extraction and extraction.mail
            else parse_gmail_detail_request(message)
        )
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "메일 상세 조회 대상을 찾지 못했습니다.\n같은 대화에서 먼저 메일 목록을 보여준 뒤 '1번 메일 상세 보여줘'처럼 요청하거나 'message id:xxxxx' 형식으로 직접 지정해 주세요.",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent == "macos_note_create":
        parsed = parse_macos_note_request(message)
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "macOS 메모 요청을 이해하지 못했습니다. 예: 메모에 제목 주간 점검 내용 브라우저 러너와 Slack 상태 확인 저장해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent == "macos_reminder_create":
        parsed = parse_macos_reminder_request(message)
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "미리알림 요청을 이해하지 못했습니다. 예: 미리알림에 장보기 추가해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent == "macos_volume_set":
        parsed = parse_macos_volume_set_request(message)
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "볼륨 값을 이해하지 못했습니다. 예: 볼륨 50으로 설정해줘",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    if intent == "macos_finder_open":
        parsed = parse_macos_finder_open_request(message)
        if parsed is None:
            return {
                "parsed_params": None,
                "reply": "Finder에서 열 경로를 이해하지 못했습니다. 예: ~/Documents 폴더 열어줘",
                "route": "validation_error",
                "action_type": intent,
            }
        return {"parsed_params": parsed}

    # calendar_summary, gmail_summary, chat, macos_volume_get, macos_darkmode_toggle — 파라미터 불필요
    return {"parsed_params": None}


# ---------------------------------------------------------------------------
# 3. check_approval — 승인 필요 여부 확인
# ---------------------------------------------------------------------------

def check_approval(state: AssistantState) -> dict:
    intent = state["intent"]
    if intent not in ACTION_LABELS:
        return {}
    if state.get("approval_granted"):
        return {}
    action_label = ACTION_LABELS[intent]
    domain_label = {
        "calendar": "일정",
        "gmail": "메일",
        "macos_note": "macOS 메모",
        "macos_reminder": "macOS 미리알림",
        "macos_volume": "macOS 볼륨",
        "macos_darkmode": "macOS 테마",
    }
    prefix = domain_label.get(intent.rsplit("_", 1)[0], "")
    reply_text = f"{prefix} {action_label} 요청입니다. 승인 후 실행합니다." if prefix else f"{action_label} 요청입니다. 승인 후 실행합니다."
    if intent == "macos_note_create":
        reply_text = "macOS 메모 생성 요청입니다. 승인 후 AppleScript로 실행합니다."
    return {
        "reply": reply_text,
        "route": "approval_required",
        "action_type": intent,
    }


# ---------------------------------------------------------------------------
# 4. execute — 실행 노드들
# ---------------------------------------------------------------------------

def execute_calendar_summary(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    memory_context = state.get("memory_context")
    extraction = state.get("extraction")

    extra_payload: dict[str, str] | None = None
    if extraction and extraction.calendar:
        cal = extraction.calendar
        extra = {}
        if cal.search_time_min:
            extra["searchTimeMin"] = cal.search_time_min
        if cal.search_time_max:
            extra["searchTimeMax"] = cal.search_time_max
        if cal.search_title:
            extra["searchTitle"] = cal.search_title
        if extra:
            extra_payload = extra

    if settings.n8n_webhook_path:
        reply = run_n8n_automation(message, channel, session_id, user_id, settings.n8n_webhook_path, extra_payload)
        if reply is not None:
            return {"reply": reply, "route": "n8n", "action_type": None}
    fallback_reply, fallback_route = _generate_reply_with_external_fallback(message, channel, memory_context)
    return {"reply": fallback_reply, "route": fallback_route, "action_type": None}


def execute_calendar_write(state: AssistantState) -> dict:
    intent = state["intent"]
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    webhook_path = {
        "calendar_create": settings.n8n_calendar_create_webhook_path,
        "calendar_update": settings.n8n_calendar_update_webhook_path,
        "calendar_delete": settings.n8n_calendar_delete_webhook_path,
    }[intent]
    reply = run_n8n_automation(message, channel, session_id, user_id, webhook_path, parsed)
    if reply is not None:
        return {"reply": reply, "route": "n8n", "action_type": intent}
    return {
        "reply": "승인된 일정 작업 실행에 실패했습니다. n8n workflow 또는 자격 증명을 확인하세요.",
        "route": "n8n_fallback",
        "action_type": intent,
    }


def execute_gmail_compose(state: AssistantState) -> dict:
    intent = state["intent"]
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    webhook_path = (
        settings.n8n_gmail_draft_webhook_path
        if intent == "gmail_draft"
        else settings.n8n_gmail_send_webhook_path
    )
    reply = run_n8n_automation(message, channel, session_id, user_id, webhook_path, parsed)
    if reply is not None:
        return {"reply": reply, "route": "n8n", "action_type": intent}
    return {
        "reply": "승인된 메일 작업 실행에 실패했습니다. n8n Gmail workflow 또는 credential 연결 상태를 확인하세요.",
        "route": "n8n_fallback",
        "action_type": intent,
    }


def execute_gmail_reply(state: AssistantState) -> dict:
    intent = state["intent"]
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    reply = run_n8n_automation(message, channel, session_id, user_id, settings.n8n_gmail_reply_webhook_path, parsed)
    if reply is not None:
        return {"reply": reply, "route": "n8n", "action_type": intent}
    return {
        "reply": "승인된 메일 회신 실행에 실패했습니다. n8n Gmail reply workflow 또는 credential 연결 상태를 확인하세요.",
        "route": "n8n_fallback",
        "action_type": intent,
    }


def execute_gmail_summary(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    extraction = state.get("extraction")

    extra_payload: dict[str, str] | None = None
    if extraction and extraction.mail:
        mail = extraction.mail
        extra: dict[str, str] = {}
        if mail.search_query:
            extra["searchQuery"] = mail.search_query
        if mail.limit:
            extra["limit"] = str(mail.limit)
        if mail.cursor:
            extra["cursor"] = mail.cursor
        if mail.group_by_date is not None:
            extra["groupByDate"] = "true" if mail.group_by_date else "false"
        if extra:
            extra_payload = extra

    if settings.n8n_gmail_webhook_path:
        raw_body = run_n8n_automation_raw(
            message, channel, session_id, user_id,
            settings.n8n_gmail_webhook_path, extra_payload,
        )
        if raw_body is not None:
            reply = format_gmail_summary(raw_body, channel)
            # n8n items를 후보 목록으로 저장 (후속 참조 대화 지원)
            items = raw_body.get("items") or []
            candidates = [
                {
                    "index": i,
                    "label": item.get("subject", ""),
                    "raw": f"{item.get('sender', '')} - {item.get('subject', '')}",
                    "sender": item.get("sender", ""),
                    "snippet": item.get("snippet", ""),
                    "date": item.get("date", ""),
                    "message_id": item.get("messageId") or item.get("message_id") or item.get("id", ""),
                    "thread_id": item.get("threadId") or item.get("thread_id") or "",
                }
                for i, item in enumerate(items)
            ] if len(items) >= 2 else []
            return {
                "reply": reply,
                "route": "n8n",
                "action_type": None,
                "last_candidates": candidates or None,
                "mail_result_context": _build_mail_result_context(raw_body, items, mode="list"),
            }
    return {
        "reply": "Gmail 자동화를 실행하지 못했습니다. n8n Gmail credential 연결 상태를 확인하세요.",
        "route": "n8n_fallback",
        "action_type": None,
    }


def execute_gmail_detail(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    if not settings.n8n_gmail_detail_webhook_path:
        return {
            "reply": "Gmail 상세 조회 workflow 경로가 설정되지 않았습니다. N8N_GMAIL_DETAIL_WEBHOOK_PATH를 확인하세요.",
            "route": "n8n_fallback",
            "action_type": None,
        }

    raw_body = run_n8n_automation_raw(
        message,
        channel,
        session_id,
        user_id,
        settings.n8n_gmail_detail_webhook_path,
        parsed,
    )
    if raw_body is not None:
        reply = raw_body.get("reply") if isinstance(raw_body.get("reply"), str) else "메일 상세 정보를 조회했습니다."
        selected_item = {
            "messageId": raw_body.get("messageId") or raw_body.get("message_id"),
            "threadId": raw_body.get("threadId") or raw_body.get("thread_id"),
        }
        return {
            "reply": reply,
            "route": "n8n",
            "action_type": None,
            "mail_result_context": _build_mail_result_context(raw_body, [], mode="detail", selected_item=selected_item),
        }
    return {
        "reply": "Gmail 상세 조회를 실행하지 못했습니다. n8n workflow 또는 Gmail credential 상태를 확인하세요.",
        "route": "n8n_fallback",
        "action_type": None,
    }


def execute_macos_note(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    reply = run_macos_automation(message, channel, session_id, user_id, "macos/notes", parsed)
    if reply is not None:
        return {"reply": reply, "route": "macos", "action_type": "macos_note_create"}
    return {
        "reply": "승인된 macOS 메모 실행에 실패했습니다. 호스트 macOS runner 실행 상태와 Notes 자동화 권한을 확인하세요.",
        "route": "macos_fallback",
        "action_type": "macos_note_create",
    }


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


def execute_macos_reminder(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    reply = run_macos_automation(message, channel, session_id, user_id, "macos/reminders", parsed)
    if reply is not None:
        return {"reply": reply, "route": "macos", "action_type": "macos_reminder_create"}
    return {
        "reply": "macOS 미리알림 실행에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
        "route": "macos_fallback",
        "action_type": "macos_reminder_create",
    }


def execute_macos_volume_get(state: AssistantState) -> dict:
    reply = run_macos_get("macos/system/volume")
    if reply is not None:
        return {"reply": reply, "route": "macos", "action_type": "macos_volume_get"}
    return {
        "reply": "macOS 볼륨 확인에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
        "route": "macos_fallback",
        "action_type": "macos_volume_get",
    }


def execute_macos_volume_set(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    reply = run_macos_automation(message, channel, session_id, user_id, "macos/system/volume", parsed)
    if reply is not None:
        return {"reply": reply, "route": "macos", "action_type": "macos_volume_set"}
    return {
        "reply": "macOS 볼륨 변경에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
        "route": "macos_fallback",
        "action_type": "macos_volume_set",
    }


def execute_macos_darkmode(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")

    reply = run_macos_automation(message, channel, session_id, user_id, "macos/system/darkmode", {})
    if reply is not None:
        return {"reply": reply, "route": "macos", "action_type": "macos_darkmode_toggle"}
    return {
        "reply": "macOS 다크모드 전환에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
        "route": "macos_fallback",
        "action_type": "macos_darkmode_toggle",
    }


def execute_macos_finder(state: AssistantState) -> dict:
    message, channel = state["message"], state.get("channel", "")
    session_id, user_id = state.get("session_id", ""), state.get("user_id")
    parsed = state.get("parsed_params")

    reply = run_macos_automation(message, channel, session_id, user_id, "macos/finder/open", parsed)
    if reply is not None:
        return {"reply": reply, "route": "macos", "action_type": "macos_finder_open"}
    return {
        "reply": "Finder 폴더 열기에 실패했습니다. macOS runner 실행 상태를 확인하세요.",
        "route": "macos_fallback",
        "action_type": "macos_finder_open",
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
