"""macOS 도메인 스킬 메타데이터 — 시스템 제어, Finder, Reminders."""

from app.skills.base import SkillDescriptor

MACOS_REMINDER_CREATE_SKILL = SkillDescriptor(
    skill_id="macos_reminder_create",
    name="미리알림 추가",
    description="macOS Reminders 앱에 미리알림을 추가한다.",
    domain="macos",
    action="reminder_create",
    trigger_keywords=["미리알림", "리마인더", "reminder", "할일", "할 일", "추가", "등록", "만들"],
    intent_examples=["미리알림에 장보기 추가해줘", "내일 오전 9시 은행 가기 리마인더 만들어줘"],
    disambiguation_hints=["Reminders 앱 쓰기 작업", "승인 필요"],
    executor_type="macos",
    executor_ref="MACOS_RUNNER_BASE_URL",
    approval_required=True,
    risk_level="medium",
)

MACOS_VOLUME_GET_SKILL = SkillDescriptor(
    skill_id="macos_volume_get",
    name="볼륨 확인",
    description="현재 macOS 시스템 볼륨을 확인한다.",
    domain="macos",
    action="volume_get",
    trigger_keywords=["볼륨", "소리", "volume", "사운드", "음량"],
    intent_examples=["현재 볼륨 알려줘", "소리 얼마나 켜져 있어?"],
    disambiguation_hints=["조회 전용", "숫자 지정이 없으면 volume_get 우선"],
    executor_type="macos",
    executor_ref="MACOS_RUNNER_BASE_URL",
    approval_required=False,
    risk_level="low",
)

MACOS_VOLUME_SET_SKILL = SkillDescriptor(
    skill_id="macos_volume_set",
    name="볼륨 설정",
    description="macOS 시스템 볼륨을 지정 수준으로 변경한다.",
    domain="macos",
    action="volume_set",
    trigger_keywords=["볼륨", "소리", "volume", "사운드", "음량", "설정", "변경", "조절", "높여", "낮춰", "줄여", "올려"],
    intent_examples=["볼륨 30으로 바꿔줘", "소리 50으로 설정해줘"],
    disambiguation_hints=["상태 변경", "승인 필요"],
    executor_type="macos",
    executor_ref="MACOS_RUNNER_BASE_URL",
    approval_required=True,
    risk_level="low",
)

MACOS_DARKMODE_TOGGLE_SKILL = SkillDescriptor(
    skill_id="macos_darkmode_toggle",
    name="다크모드 전환",
    description="macOS 다크모드와 라이트모드를 전환한다.",
    domain="macos",
    action="darkmode_toggle",
    trigger_keywords=["다크모드", "다크 모드", "라이트모드", "라이트 모드", "dark mode", "밝기", "테마"],
    intent_examples=["다크모드 켜줘", "라이트 모드로 바꿔줘"],
    disambiguation_hints=["시스템 테마 변경", "승인 필요"],
    executor_type="macos",
    executor_ref="MACOS_RUNNER_BASE_URL",
    approval_required=True,
    risk_level="low",
)

MACOS_FINDER_OPEN_SKILL = SkillDescriptor(
    skill_id="macos_finder_open",
    name="Finder 폴더 열기",
    description="macOS Finder에서 지정 폴더를 연다.",
    domain="macos",
    action="finder_open",
    trigger_keywords=["파인더", "finder", "폴더", "디렉토리", "열어", "열기"],
    intent_examples=["파인더로 Downloads 폴더 열어줘", "~/Documents 열어줘"],
    disambiguation_hints=["로컬 경로 열기", "파일 조작은 아님"],
    executor_type="macos",
    executor_ref="MACOS_RUNNER_BASE_URL",
    approval_required=False,
    risk_level="low",
)

SKILLS = [
    MACOS_REMINDER_CREATE_SKILL,
    MACOS_VOLUME_GET_SKILL,
    MACOS_VOLUME_SET_SKILL,
    MACOS_DARKMODE_TOGGLE_SKILL,
    MACOS_FINDER_OPEN_SKILL,
]
