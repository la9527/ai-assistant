"""검색 도메인 스킬 메타데이터 — 웹 검색 및 정보 수집."""

from app.skills.base import SkillDescriptor

WEB_SEARCH_SKILL = SkillDescriptor(
    skill_id="web_search",
    name="웹 검색",
    description="인터넷에서 정보를 검색하고 결과를 요약한다.",
    domain="search",
    action="search",
    trigger_keywords=[
        "검색", "찾아", "찾아줘", "search",
        "알려줘", "알려 줘", "뭐야", "뭔가요",
        "최신", "뉴스", "정보",
        "어떻게", "방법",
        "가격", "날씨", "환율", "주가",
    ],
    executor_type="api",
    executor_ref="web_search",
    approval_required=False,
    risk_level="low",
)

SKILLS = [
    WEB_SEARCH_SKILL,
]
