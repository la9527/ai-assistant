"""macOS 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

from pydantic import BaseModel

from app.skills.base import BaseSkill
from app.skills.macos.descriptor import MACOS_DARKMODE_TOGGLE_SKILL
from app.skills.macos.descriptor import MACOS_FINDER_OPEN_SKILL
from app.skills.macos.descriptor import MACOS_REMINDER_CREATE_SKILL
from app.skills.macos.descriptor import MACOS_VOLUME_GET_SKILL
from app.skills.macos.descriptor import MACOS_VOLUME_SET_SKILL


class _BaseMacOSSkill(BaseSkill):
    descriptor_model = MACOS_VOLUME_GET_SKILL

    def descriptor(self):
        return self.descriptor_model

    async def extract(self, message: str, context: dict) -> BaseModel | None:
        return context.get("structured_extraction")


class MacOSReminderCreateSkill(_BaseMacOSSkill):
    descriptor_model = MACOS_REMINDER_CREATE_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        macos = getattr(params, "macos", None)
        if macos and macos.reminder_name:
            return []
        return [] if automation_module.parse_macos_reminder_request(params.raw_message) else ["name"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module

        macos = getattr(params, "macos", None)
        parsed = (
            {
                "name": macos.reminder_name,
                "note": macos.reminder_note or "",
                "list_name": macos.reminder_list or "Reminders",
            }
            if macos and macos.reminder_name
            else automation_module.parse_macos_reminder_request(context["message"])
        )
        reply = automation_module.run_macos_automation(
            context["message"], context["channel"], context["session_id"], context.get("user_id"), "macos/reminders", parsed
        )
        if reply is not None:
            return {"reply": reply, "route": "macos"}
        return {"reply": "macOS 미리알림 실행에 실패했습니다. macOS runner 실행 상태를 확인하세요.", "route": "macos_fallback"}


class MacOSVolumeGetSkill(_BaseMacOSSkill):
    descriptor_model = MACOS_VOLUME_GET_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        return []

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module

        reply = automation_module.run_macos_get("macos/system/volume")
        if reply is not None:
            return {"reply": reply, "route": "macos"}
        return {"reply": "macOS 볼륨 확인에 실패했습니다. macOS runner 실행 상태를 확인하세요.", "route": "macos_fallback"}


class MacOSVolumeSetSkill(_BaseMacOSSkill):
    descriptor_model = MACOS_VOLUME_SET_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        macos = getattr(params, "macos", None)
        if macos and macos.volume_level is not None:
            return []
        return [] if automation_module.parse_macos_volume_set_request(params.raw_message) else ["level"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module

        macos = getattr(params, "macos", None)
        parsed = {"level": macos.volume_level} if macos and macos.volume_level is not None else automation_module.parse_macos_volume_set_request(context["message"])
        reply = automation_module.run_macos_automation(
            context["message"], context["channel"], context["session_id"], context.get("user_id"), "macos/system/volume", parsed
        )
        if reply is not None:
            return {"reply": reply, "route": "macos"}
        return {"reply": "macOS 볼륨 변경에 실패했습니다. macOS runner 실행 상태를 확인하세요.", "route": "macos_fallback"}


class MacOSDarkModeToggleSkill(_BaseMacOSSkill):
    descriptor_model = MACOS_DARKMODE_TOGGLE_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        return []

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module

        reply = automation_module.run_macos_automation(
            context["message"], context["channel"], context["session_id"], context.get("user_id"), "macos/system/darkmode", {}
        )
        if reply is not None:
            return {"reply": reply, "route": "macos"}
        return {"reply": "macOS 다크모드 전환에 실패했습니다. macOS runner 실행 상태를 확인하세요.", "route": "macos_fallback"}


class MacOSFinderOpenSkill(_BaseMacOSSkill):
    descriptor_model = MACOS_FINDER_OPEN_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        from app import automation as automation_module

        macos = getattr(params, "macos", None)
        if macos and macos.finder_path:
            return []
        return [] if automation_module.parse_macos_finder_open_request(params.raw_message) else ["path"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app import automation as automation_module

        macos = getattr(params, "macos", None)
        parsed = {"path": macos.finder_path} if macos and macos.finder_path else automation_module.parse_macos_finder_open_request(context["message"])
        reply = automation_module.run_macos_automation(
            context["message"], context["channel"], context["session_id"], context.get("user_id"), "macos/finder/open", parsed
        )
        if reply is not None:
            return {"reply": reply, "route": "macos"}
        return {"reply": "Finder 폴더 열기에 실패했습니다. macOS runner 실행 상태를 확인하세요.", "route": "macos_fallback"}


SKILL_IMPLEMENTATIONS = [
    MacOSReminderCreateSkill(),
    MacOSVolumeGetSkill(),
    MacOSVolumeSetSkill(),
    MacOSDarkModeToggleSkill(),
    MacOSFinderOpenSkill(),
]