"""mail 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

from pydantic import BaseModel

from app.skills.base import BaseSkill
from app.skills.mail.descriptor import GMAIL_DETAIL_SKILL
from app.skills.mail.descriptor import GMAIL_DRAFT_SKILL
from app.skills.mail.descriptor import GMAIL_LIST_SKILL
from app.skills.mail.descriptor import GMAIL_REPLY_SKILL
from app.skills.mail.descriptor import GMAIL_SEND_SKILL
from app.skills.mail.descriptor import GMAIL_SUMMARY_SKILL
from app.skills.mail.descriptor import GMAIL_THREAD_REPLY_SKILL


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


SKILL_IMPLEMENTATIONS = [
    GmailSummarySkill(),
    GmailListSkill(),
    GmailDetailSkill(),
    GmailDraftSkill(),
    GmailSendSkill(),
    GmailReplySkill(),
    GmailThreadReplySkill(),
]