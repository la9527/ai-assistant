"""mail 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

from pydantic import BaseModel

from app.skills.base import BaseSkill
from app.skills.mail.descriptor import GMAIL_DETAIL_SKILL
from app.skills.mail.descriptor import GMAIL_DRAFT_SKILL
from app.skills.mail.descriptor import GMAIL_LIST_SKILL
from app.skills.mail.descriptor import GMAIL_ARCHIVE_SKILL
from app.skills.mail.descriptor import GMAIL_MARK_READ_SKILL
from app.skills.mail.descriptor import GMAIL_REPLY_SKILL
from app.skills.mail.descriptor import GMAIL_SEND_SKILL
from app.skills.mail.descriptor import GMAIL_SUMMARY_SKILL
from app.skills.mail.descriptor import GMAIL_THREAD_SKILL
from app.skills.mail.descriptor import GMAIL_THREAD_REPLY_SKILL
from app.skills.mail.descriptor import GMAIL_TRASH_SKILL


class _BaseMailSkill(BaseSkill):
    descriptor_model = GMAIL_SUMMARY_SKILL

    def descriptor(self):
        return self.descriptor_model

    async def extract(self, message: str, context: dict) -> BaseModel | None:
        extraction = context.get("structured_extraction")
        if extraction is not None:
            return extraction
        from app.automation import extract_structured_request

        return extract_structured_request(message, context.get("channel"))


class GmailSummarySkill(_BaseMailSkill):
    descriptor_model = GMAIL_SUMMARY_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        return []

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings
        from app.llm import format_gmail_summary

        extraction = params
        extra_payload: dict[str, str] | None = None
        if extraction.mail:
            extra: dict[str, str] = {}
            if extraction.mail.search_query:
                extra["searchQuery"] = extraction.mail.search_query
            if extraction.mail.limit:
                extra["limit"] = str(extraction.mail.limit)
            if extraction.mail.cursor:
                extra["cursor"] = extraction.mail.cursor
            if extraction.mail.group_by_date is not None:
                extra["groupByDate"] = "true" if extraction.mail.group_by_date else "false"
            # filters 에서 mailboxScope 추출 (n8n workflow 의 labelIds 결정에 사용)
            if extraction.mail.filters and extraction.mail.filters.mailbox_scope:
                extra["mailboxScope"] = extraction.mail.filters.mailbox_scope
            if extra:
                extra_payload = extra

        raw_body = automation_module.run_n8n_automation_raw(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            settings.n8n_gmail_webhook_path,
            extra_payload,
        )
        if raw_body is None:
            return {
                "reply": "Gmail 목록 조회를 실행하지 못했습니다. n8n Gmail credential 연결 상태를 확인하세요.",
                "route": "n8n_fallback",
            }
        raw_body = automation_module._merge_mail_request_context(raw_body, extra_payload)

        items = raw_body.get("items") or []
        candidates = [
            {
                "index": i,
                "label": item.get("subject", ""),
                "raw": f"{item.get('sender', '')} - {item.get('subject', '')}",
                "sender": item.get("sender", ""),
                "toRecipients": item.get("toRecipients") or item.get("to_recipients") or "",
                "snippet": item.get("snippet", ""),
                "date": item.get("date", ""),
                "message_id": item.get("messageId") or item.get("message_id") or item.get("id", ""),
                "thread_id": item.get("threadId") or item.get("thread_id") or "",
            }
            for i, item in enumerate(items)
        ] if len(items) >= 2 else []
        return {
            "reply": format_gmail_summary(raw_body, context["channel"]),
            "route": "n8n",
            "last_candidates": candidates or None,
            "mail_result_context": automation_module._build_mail_result_context(raw_body, items, mode="list"),
        }


class GmailListSkill(GmailSummarySkill):
    descriptor_model = GMAIL_LIST_SKILL


class GmailDetailSkill(_BaseMailSkill):
    descriptor_model = GMAIL_DETAIL_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        extraction = params
        candidate_data_list = extraction.metadata.get("candidate_data_list") if extraction.metadata else None
        if isinstance(candidate_data_list, list) and candidate_data_list:
            return []
        parsed = (
            automation_module._mail_payload_to_detail_request(extraction.mail)
            if extraction.mail
            else automation_module.parse_gmail_detail_request(extraction.raw_message)
        )
        return [] if parsed is not None else ["target"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings
        from app.llm import format_gmail_detail

        extraction = params
        candidate_data_list = extraction.metadata.get("candidate_data_list") if extraction.metadata else None
        if isinstance(candidate_data_list, list) and len(candidate_data_list) >= 2:
            replies: list[str] = []
            selected_items: list[dict] = []
            for position, candidate in enumerate(candidate_data_list, start=1):
                candidate_payload: dict[str, str] = {
                    "detail_level": extraction.mail.detail_level if extraction.mail and extraction.mail.detail_level else "brief",
                }
                message_id = candidate.get("message_id") or candidate.get("messageId")
                thread_id = candidate.get("thread_id") or candidate.get("threadId")
                if message_id:
                    candidate_payload["message_id"] = str(message_id)
                if thread_id:
                    candidate_payload["thread_id"] = str(thread_id)
                if candidate.get("label"):
                    candidate_payload["subject"] = str(candidate["label"])
                raw_body = automation_module.run_n8n_automation_raw(
                    context["message"],
                    context["channel"],
                    context["session_id"],
                    context.get("user_id"),
                    settings.n8n_gmail_detail_webhook_path,
                    candidate_payload,
                )
                if raw_body is None:
                    continue
                selected_items.append(
                    {
                        "messageId": raw_body.get("messageId") or raw_body.get("message_id") or message_id,
                        "threadId": raw_body.get("threadId") or raw_body.get("thread_id") or thread_id,
                    }
                )
                replies.append(f"**{position}) 선택한 메일**\n{format_gmail_detail(raw_body, context['channel'])}")

            if not replies:
                return {
                    "reply": "선택한 메일 상세 조회를 실행하지 못했습니다. n8n Gmail detail workflow 또는 credential 연결 상태를 확인하세요.",
                    "route": "n8n_fallback",
                }

            return {
                "reply": "\n\n".join(replies),
                "route": "n8n",
                "mail_result_context": automation_module._build_mail_result_context(
                    {"items": selected_items},
                    selected_items,
                    mode="detail",
                    selected_item=selected_items[0] if selected_items else None,
                ),
            }

        parsed = (
            automation_module._mail_payload_to_detail_request(extraction.mail)
            if extraction.mail
            else automation_module.parse_gmail_detail_request(context["message"])
        )
        raw_body = automation_module.run_n8n_automation_raw(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            settings.n8n_gmail_detail_webhook_path,
            parsed,
        )
        if raw_body is None:
            return {
                "reply": "Gmail 상세 조회를 실행하지 못했습니다. n8n Gmail detail workflow 또는 credential 연결 상태를 확인하세요.",
                "route": "n8n_fallback",
            }

        selected_item = {
            "messageId": raw_body.get("messageId") or raw_body.get("message_id"),
            "threadId": raw_body.get("threadId") or raw_body.get("thread_id"),
        }
        return {
            "reply": format_gmail_detail(raw_body, context["channel"]),
            "route": "n8n",
            "mail_result_context": automation_module._build_mail_result_context(raw_body, [], mode="detail", selected_item=selected_item),
        }


class GmailThreadSkill(_BaseMailSkill):
    descriptor_model = GMAIL_THREAD_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        extraction = params
        parsed = (
            automation_module._mail_payload_to_thread_request(extraction.mail)
            if extraction.mail
            else automation_module.parse_gmail_thread_request(extraction.raw_message)
        )
        return [] if parsed is not None else ["thread"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings
        from app.llm import format_gmail_thread

        extraction = params
        parsed = (
            automation_module._mail_payload_to_thread_request(extraction.mail)
            if extraction.mail
            else automation_module.parse_gmail_thread_request(context["message"])
        )
        raw_body = automation_module.run_n8n_automation_raw(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            settings.n8n_gmail_thread_webhook_path,
            parsed,
        )
        if raw_body is None:
            return {
                "reply": "Gmail 스레드 조회를 실행하지 못했습니다. n8n Gmail thread workflow 또는 credential 연결 상태를 확인하세요.",
                "route": "n8n_fallback",
            }

        selected_item = {
            "messageId": raw_body.get("selectedMessageId") or raw_body.get("messageId") or raw_body.get("message_id"),
            "threadId": raw_body.get("threadId") or raw_body.get("thread_id"),
        }
        return {
            "reply": format_gmail_thread(raw_body, context["channel"]),
            "route": "n8n",
            "mail_result_context": automation_module._build_mail_result_context(
                raw_body,
                raw_body.get("items") or [],
                mode="thread",
                selected_item=selected_item,
            ),
        }


class _BaseMailComposeSkill(_BaseMailSkill):
    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        extraction = params
        parsed = (
            automation_module._mail_payload_to_compose_request(extraction.mail, self.descriptor().skill_id)
            if extraction.mail
            else automation_module.parse_gmail_compose_request(extraction.raw_message, self.descriptor().skill_id)
        )
        return [] if parsed is not None else ["recipients", "subject", "body"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings
        from app.llm import format_gmail_action_reply

        extraction = params
        intent = self.descriptor().skill_id
        parsed = (
            automation_module._mail_payload_to_compose_request(extraction.mail, intent)
            if extraction.mail
            else automation_module.parse_gmail_compose_request(context["message"], intent)
        )
        webhook_path = (
            settings.n8n_gmail_draft_webhook_path
            if intent == "gmail_draft"
            else settings.n8n_gmail_send_webhook_path
        )
        reply = automation_module.run_n8n_automation(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            webhook_path,
            parsed,
        )
        if reply is not None:
            return {"reply": format_gmail_action_reply(reply, context["channel"]), "route": "n8n"}
        return {
            "reply": "승인된 메일 작업 실행에 실패했습니다. n8n Gmail workflow 또는 credential 연결 상태를 확인하세요.",
            "route": "n8n_fallback",
        }


class GmailDraftSkill(_BaseMailComposeSkill):
    descriptor_model = GMAIL_DRAFT_SKILL


class GmailSendSkill(_BaseMailComposeSkill):
    descriptor_model = GMAIL_SEND_SKILL


class _BaseMailReplySkill(_BaseMailSkill):
    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        extraction = params
        parsed = (
            automation_module._mail_payload_to_reply_request(extraction.mail, self.descriptor().skill_id)
            if extraction.mail
            else automation_module.parse_gmail_reply_request(extraction.raw_message, self.descriptor().skill_id)
        )
        return [] if parsed is not None else ["message", "target"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings
        from app.llm import format_gmail_action_reply

        extraction = params
        intent = self.descriptor().skill_id
        parsed = (
            automation_module._mail_payload_to_reply_request(extraction.mail, intent)
            if extraction.mail
            else automation_module.parse_gmail_reply_request(context["message"], intent)
        )
        reply = automation_module.run_n8n_automation(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            settings.n8n_gmail_reply_webhook_path,
            parsed,
        )
        if reply is not None:
            return {"reply": format_gmail_action_reply(reply, context["channel"]), "route": "n8n"}
        return {
            "reply": "승인된 메일 회신 실행에 실패했습니다. n8n Gmail reply workflow 또는 credential 연결 상태를 확인하세요.",
            "route": "n8n_fallback",
        }


class GmailReplySkill(_BaseMailReplySkill):
    descriptor_model = GMAIL_REPLY_SKILL


class GmailThreadReplySkill(_BaseMailReplySkill):
    descriptor_model = GMAIL_THREAD_REPLY_SKILL


class _BaseMailBulkActionSkill(_BaseMailSkill):
    """preview-first 패턴의 파괴적 메일 액션 공통 기반."""

    _action_label: str = "작업"
    _action_verb: str = "처리"

    async def validate(self, params: BaseModel) -> list[str]:
        extraction = params
        if extraction.mail and extraction.mail.filters:
            return []
        return ["검색 조건을 지정해주세요 (기간, 카테고리, 발신자 등)"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app.automation import _compile_gmail_query
        from app.automation import _normalize_mail_query_filters
        from app.automation import run_n8n_automation_raw
        from app.config import settings

        extraction = params
        filters = extraction.mail.filters if extraction.mail else None
        if not filters:
            return {
                "reply": f"{self._action_label} 대상을 특정할 수 없습니다. 검색 조건을 지정해주세요.",
                "route": "n8n_fallback",
            }

        normalized = _normalize_mail_query_filters(filters)
        query = _compile_gmail_query(normalized)

        extra_payload: dict[str, str] = {"searchQuery": query, "limit": "30"}
        if normalized.mailbox_scope:
            extra_payload["mailboxScope"] = normalized.mailbox_scope

        raw_body = run_n8n_automation_raw(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            settings.n8n_gmail_webhook_path,
            extra_payload,
        )
        if raw_body is None:
            return {
                "reply": "대상 메일 조회에 실패했습니다. n8n Gmail credential 연결 상태를 확인하세요.",
                "route": "n8n_fallback",
            }

        items = raw_body.get("items") or []
        count = len(items)
        if count == 0:
            return {
                "reply": f"조건에 맞는 메일이 없습니다. (검색 쿼리: {query})",
                "route": "n8n",
            }

        sample = items[:5]
        sample_lines = "\n".join(
            f"  {i + 1}. {item.get('sender', '')} — {item.get('subject', '')}"
            for i, item in enumerate(sample)
        )
        reply = (
            f"조건에 맞는 메일 **{count}건**을 찾았습니다.\n\n"
            f"**최근 {len(sample)}건 미리보기:**\n{sample_lines}\n\n"
            f"승인하면 이 {count}건을 {self._action_verb}합니다."
        )
        message_ids = [
            item.get("messageId") or item.get("message_id") or item.get("id", "")
            for item in items
        ]
        return {
            "reply": reply,
            "route": "n8n",
            "approval_context": {
                "action": self.descriptor().skill_id,
                "message_ids": message_ids,
                "count": count,
                "query": query,
            },
        }


class GmailTrashSkill(_BaseMailBulkActionSkill):
    descriptor_model = GMAIL_TRASH_SKILL
    _action_label = "삭제"
    _action_verb = "휴지통으로 이동"


class GmailArchiveSkill(_BaseMailBulkActionSkill):
    descriptor_model = GMAIL_ARCHIVE_SKILL
    _action_label = "보관"
    _action_verb = "보관 처리"


class GmailMarkReadSkill(_BaseMailBulkActionSkill):
    descriptor_model = GMAIL_MARK_READ_SKILL
    _action_label = "읽음 처리"
    _action_verb = "읽음 처리"


SKILL_IMPLEMENTATIONS = [
    GmailSummarySkill(),
    GmailListSkill(),
    GmailDetailSkill(),
    GmailThreadSkill(),
    GmailDraftSkill(),
    GmailSendSkill(),
    GmailReplySkill(),
    GmailThreadReplySkill(),
    GmailTrashSkill(),
    GmailArchiveSkill(),
    GmailMarkReadSkill(),
]