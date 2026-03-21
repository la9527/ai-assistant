"""브라우저 도메인 스킬 메타데이터 — 웹 페이지 읽기, 스크린샷, 브라우저 검색."""

from app.skills.base import SkillDescriptor

BROWSER_READ_SKILL = SkillDescriptor(
    skill_id="browser_read",
    name="웹 페이지 읽기",
    description="URL을 방문하여 페이지 제목, 본문 요약, 헤딩을 추출한다.",
    domain="browser",
    action="read",
    trigger_keywords=[
        "페이지", "읽어", "읽어줘", "페이지 읽기",
        "사이트", "웹사이트", "url", "열어",
    ],
    intent_examples=["https://example.com 읽어줘", "이 사이트 내용 요약해줘"],
    disambiguation_hints=["URL 기반 읽기", "검색이 아니라 특정 페이지 조회"],
    executor_type="api",
    executor_ref="browser_read",
    approval_required=False,
    risk_level="low",
)

BROWSER_SCREENSHOT_SKILL = SkillDescriptor(
    skill_id="browser_screenshot",
    name="웹 페이지 스크린샷",
    description="URL을 방문하여 페이지 스크린샷을 캡처한다.",
    domain="browser",
    action="screenshot",
    trigger_keywords=[
        "스크린샷", "screenshot", "캡처", "화면",
    ],
    intent_examples=["https://example.com 화면 캡처해줘", "이 페이지 스크린샷 찍어줘"],
    disambiguation_hints=["페이지 이미지 캡처", "URL 또는 현재 페이지 대상"],
    executor_type="api",
    executor_ref="browser_screenshot",
    approval_required=False,
    risk_level="low",
)

BROWSER_SEARCH_SKILL = SkillDescriptor(
    skill_id="browser_search",
    name="브라우저 웹 검색",
    description="Google 검색을 브라우저를 통해 수행하고 결과를 반환한다.",
    domain="browser",
    action="search",
    trigger_keywords=[
        "구글", "google", "브라우저 검색", "브라우저로 검색",
    ],
    intent_examples=["구글에서 맥미니 MLX 성능 검색해줘", "브라우저로 환율 검색해줘"],
    disambiguation_hints=["검색 결과 페이지를 브라우저 기반으로 확보", "일반 웹 검색과 구분"],
    executor_type="api",
    executor_ref="browser_search",
    approval_required=False,
    risk_level="low",
)

SKILLS = [
    BROWSER_READ_SKILL,
    BROWSER_SCREENSHOT_SKILL,
    BROWSER_SEARCH_SKILL,
]
