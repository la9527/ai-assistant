"""note 도메인 스킬 메타데이터."""

from app.skills.base import SkillDescriptor

MACOS_NOTE_CREATE_SKILL = SkillDescriptor(
    skill_id="macos_note_create",
    name="메모 작성",
    description="macOS Notes 앱에 새 메모를 추가한다. 제목과 본문이 필요하다.",
    domain="note",
    action="create",
    trigger_keywords=["메모", "노트", "notes", "추가", "작성", "저장", "기록", "남겨", "만들"],
    executor_type="macos",
    executor_ref="MACOS_RUNNER_BASE_URL",
    approval_required=True,
    risk_level="medium",
)

SKILLS = [
    MACOS_NOTE_CREATE_SKILL,
]
