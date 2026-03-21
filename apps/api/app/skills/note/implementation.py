"""note 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

from pydantic import BaseModel

from app.skills.base import BaseSkill
from app.skills.note.descriptor import MACOS_NOTE_CREATE_SKILL


class MacOSNoteCreateSkill(BaseSkill):
    def descriptor(self):
        return MACOS_NOTE_CREATE_SKILL

    async def extract(self, message: str, context: dict) -> BaseModel | None:
        return context.get("structured_extraction")

    def _build_note_payload(self, params: BaseModel) -> dict[str, str] | None:
        note = getattr(params, "note", None)
        if note and note.title and note.body:
            payload = {
                "title": note.title,
                "body": note.body,
            }
            if note.folder:
                payload["folder"] = note.folder
            return payload
        return None

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        parsed = self._build_note_payload(params) or automation_module.parse_macos_note_request(params.raw_message)
        return [] if parsed else ["title", "body"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module

        parsed = self._build_note_payload(params) or automation_module.parse_macos_note_request(context["message"])
        reply = automation_module.run_macos_automation(
            context["message"], context["channel"], context["session_id"], context.get("user_id"), "macos/notes", parsed
        )
        if reply is not None:
            return {"reply": reply, "route": "macos"}
        return {
            "reply": "승인된 macOS 메모 실행에 실패했습니다. 호스트 macOS runner 실행 상태와 Notes 자동화 권한을 확인하세요.",
            "route": "macos_fallback",
        }


SKILL_IMPLEMENTATIONS = [MacOSNoteCreateSkill()]