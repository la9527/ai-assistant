"""calendar 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

from pydantic import BaseModel

from app.skills.base import BaseSkill
from app.skills.calendar.descriptor import CALENDAR_CREATE_SKILL
from app.skills.calendar.descriptor import CALENDAR_DELETE_SKILL
from app.skills.calendar.descriptor import CALENDAR_SUMMARY_SKILL
from app.skills.calendar.descriptor import CALENDAR_UPDATE_SKILL


class _BaseCalendarSkill(BaseSkill):
    descriptor_model = CALENDAR_SUMMARY_SKILL

    def descriptor(self):
        return self.descriptor_model

    async def extract(self, message: str, context: dict) -> BaseModel | None:
        extraction = context.get("structured_extraction")
        if extraction is not None:
            return extraction
        from app.automation import extract_structured_request

        return extract_structured_request(message, context.get("channel"))


class CalendarSummarySkill(_BaseCalendarSkill):
    descriptor_model = CALENDAR_SUMMARY_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        return []

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings

        reply = automation_module.run_n8n_automation(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            settings.n8n_webhook_path,
        )
        if reply is not None:
            return {"reply": reply, "route": "n8n"}
        fallback_reply, _ = automation_module.generate_local_reply(
            context["message"],
            context["channel"],
            context.get("memory_context"),
        )
        return {"reply": fallback_reply, "route": "n8n_fallback"}


class _BaseCalendarMutationSkill(_BaseCalendarSkill):
    def _build_failure_reply(self, intent: str) -> str:
        action_label = {
            "calendar_create": "생성",
            "calendar_update": "변경",
            "calendar_delete": "삭제",
        }.get(intent, "처리")
        return (
            f"Google Calendar 연결이 만료되었거나 n8n workflow 응답이 비정상이라 일정 {action_label}을 완료하지 못했습니다. "
            "n8n의 Google Calendar account credential을 다시 연결한 뒤 다시 시도해 주세요."
        )

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        extraction = params
        parsed = (
            automation_module._calendar_payload_to_request(extraction.calendar, self.descriptor().skill_id)
            if extraction.calendar
            else automation_module.parse_calendar_request(extraction.raw_message, self.descriptor().skill_id)
        )
        if parsed is not None:
            return []
        if self.descriptor().skill_id == "calendar_delete":
            return ["title", "date_or_time"]
        return ["title", "date", "time"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module
        from app.config import settings

        extraction = params
        intent = self.descriptor().skill_id
        parsed = (
            automation_module._calendar_payload_to_request(extraction.calendar, intent)
            if extraction.calendar
            else automation_module.parse_calendar_request(context["message"], intent)
        )
        webhook_path = {
            "calendar_create": settings.n8n_calendar_create_webhook_path,
            "calendar_update": settings.n8n_calendar_update_webhook_path,
            "calendar_delete": settings.n8n_calendar_delete_webhook_path,
        }[intent]
        reply = automation_module.run_n8n_automation(
            context["message"],
            context["channel"],
            context["session_id"],
            context.get("user_id"),
            webhook_path,
            parsed,
        )
        if reply is not None:
            return {"reply": reply, "route": "n8n"}
        return {
            "reply": self._build_failure_reply(intent),
            "route": "n8n_fallback",
        }


class CalendarCreateSkill(_BaseCalendarMutationSkill):
    descriptor_model = CALENDAR_CREATE_SKILL


class CalendarUpdateSkill(_BaseCalendarMutationSkill):
    descriptor_model = CALENDAR_UPDATE_SKILL


class CalendarDeleteSkill(_BaseCalendarMutationSkill):
    descriptor_model = CALENDAR_DELETE_SKILL


SKILL_IMPLEMENTATIONS = [
    CalendarSummarySkill(),
    CalendarCreateSkill(),
    CalendarUpdateSkill(),
    CalendarDeleteSkill(),
]