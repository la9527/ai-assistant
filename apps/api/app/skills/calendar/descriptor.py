"""calendar 도메인 스킬 메타데이터."""

from app.skills.base import SkillDescriptor

CALENDAR_SUMMARY_SKILL = SkillDescriptor(
    skill_id="calendar_summary",
    name="오늘 일정 요약",
    description="Google Calendar에서 오늘 일정을 조회해 요약한다.",
    domain="calendar",
    action="summary",
    trigger_keywords=["일정", "캘린더", "calendar"],
    intent_examples=["오늘 일정 보여줘", "이번 주 일정 요약해줘"],
    disambiguation_hints=["조회 전용", "생성/변경/삭제 표현이 없으면 summary 우선"],
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
    intent_examples=["내일 오후 3시에 치과 일정 추가해줘", "회의 일정 잡아줘"],
    disambiguation_hints=["새 일정 생성", "승인 필요"],
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
    intent_examples=["치과 일정을 4시로 옮겨줘", "방금 만든 일정 한 시간 뒤로 미뤄줘"],
    disambiguation_hints=["기존 일정 수정", "승인 필요"],
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
    intent_examples=["오늘 저녁 회의 일정 삭제해줘", "방금 만든 일정 취소해줘"],
    disambiguation_hints=["기존 일정 삭제", "승인 필요"],
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
