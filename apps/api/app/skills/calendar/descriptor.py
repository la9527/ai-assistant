"""calendar 도메인 스킬 메타데이터."""

from app.skills.base import SkillDescriptor

CALENDAR_SUMMARY_SKILL = SkillDescriptor(
    skill_id="calendar_summary",
    name="오늘 일정 요약",
    description="Google Calendar에서 오늘 일정을 조회해 요약한다.",
    domain="calendar",
    action="summary",
    trigger_keywords=["일정", "캘린더", "calendar"],
    executor_type="n8n",
    executor_ref="N8N_WEBHOOK_PATH",
    approval_required=False,
    risk_level="low",
)

CALENDAR_CREATE_SKILL = SkillDescriptor(
    skill_id="calendar_create",
    name="일정 생성",
    description="Google Calendar에 새 일정을 추가한다. 날짜, 시간, 제목이 필요하다.",
    domain="calendar",
    action="create",
    trigger_keywords=["일정", "캘린더", "calendar", "추가", "생성", "등록", "만들", "잡아"],
    executor_type="n8n",
    executor_ref="N8N_CALENDAR_CREATE_WEBHOOK_PATH",
    approval_required=True,
    risk_level="medium",
)

CALENDAR_UPDATE_SKILL = SkillDescriptor(
    skill_id="calendar_update",
    name="일정 변경",
    description="Google Calendar 기존 일정의 시간이나 제목을 변경한다.",
    domain="calendar",
    action="update",
    trigger_keywords=["일정", "캘린더", "calendar", "변경", "수정", "옮겨", "미뤄", "당겨", "재조정"],
    executor_type="n8n",
    executor_ref="N8N_CALENDAR_UPDATE_WEBHOOK_PATH",
    approval_required=True,
    risk_level="medium",
)

CALENDAR_DELETE_SKILL = SkillDescriptor(
    skill_id="calendar_delete",
    name="일정 삭제",
    description="Google Calendar에서 기존 일정을 삭제한다. 제목이나 시간으로 대상을 특정한다.",
    domain="calendar",
    action="delete",
    trigger_keywords=["일정", "캘린더", "calendar", "삭제", "취소", "지워", "제거", "없애"],
    executor_type="n8n",
    executor_ref="N8N_CALENDAR_DELETE_WEBHOOK_PATH",
    approval_required=True,
    risk_level="medium",
)

SKILLS = [
    CALENDAR_SUMMARY_SKILL,
    CALENDAR_CREATE_SKILL,
    CALENDAR_UPDATE_SKILL,
    CALENDAR_DELETE_SKILL,
]
