"""스킬 레지스트리 및 의도 매칭 테스트."""

import unittest

from app.skills.base import SkillDescriptor
from app.skills.registry import (
    _SKILL_REGISTRY,
    classify_intent_from_registry,
    ensure_initialized,
    get_registry,
    get_skill_by_id,
    match_skills_by_keywords,
    register_skill,
)


class RegistryInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        _SKILL_REGISTRY.clear()

    def tearDown(self) -> None:
        _SKILL_REGISTRY.clear()

    def test_ensure_initialized_loads_skills(self) -> None:
        self.assertEqual(len(_SKILL_REGISTRY), 0)
        ensure_initialized()
        self.assertGreater(len(_SKILL_REGISTRY), 0)

    def test_ensure_initialized_idempotent(self) -> None:
        ensure_initialized()
        count = len(_SKILL_REGISTRY)
        ensure_initialized()
        self.assertEqual(len(_SKILL_REGISTRY), count)

    def test_get_skill_by_id(self) -> None:
        ensure_initialized()
        skill = get_skill_by_id("calendar_create")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.domain, "calendar")
        self.assertEqual(skill.action, "create")

    def test_get_skill_by_id_missing(self) -> None:
        ensure_initialized()
        self.assertIsNone(get_skill_by_id("nonexistent_skill"))

    def test_get_registry_returns_copy(self) -> None:
        ensure_initialized()
        registry = get_registry()
        original_len = len(registry)
        registry.pop()
        self.assertEqual(len(get_registry()), original_len)


class KeywordMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        _SKILL_REGISTRY.clear()
        ensure_initialized()

    def tearDown(self) -> None:
        _SKILL_REGISTRY.clear()

    def test_calendar_create_matched(self) -> None:
        results = match_skills_by_keywords("내일 일정 추가해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("calendar_create", skill_ids)

    def test_calendar_delete_matched(self) -> None:
        results = match_skills_by_keywords("내일 캘린더 일정 삭제해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("calendar_delete", skill_ids)

    def test_gmail_draft_matched(self) -> None:
        results = match_skills_by_keywords("메일 초안 작성해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("gmail_draft", skill_ids)

    def test_gmail_reply_matched(self) -> None:
        results = match_skills_by_keywords("이메일 답장 보내줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("gmail_reply", skill_ids)

    def test_macos_note_create_matched(self) -> None:
        results = match_skills_by_keywords("메모 추가해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("macos_note_create", skill_ids)

    def test_macos_reminder_matched(self) -> None:
        results = match_skills_by_keywords("미리알림 추가해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("macos_reminder_create", skill_ids)

    def test_macos_volume_set_matched(self) -> None:
        results = match_skills_by_keywords("볼륨 설정해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("macos_volume_set", skill_ids)

    def test_macos_darkmode_matched(self) -> None:
        results = match_skills_by_keywords("다크모드 전환")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("macos_darkmode_toggle", skill_ids)

    def test_macos_finder_matched(self) -> None:
        results = match_skills_by_keywords("파인더 폴더 열기")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("macos_finder_open", skill_ids)

    def test_no_match_for_chat(self) -> None:
        results = match_skills_by_keywords("안녕 오늘 기분이 좋아")
        self.assertEqual(len(results), 0)

    def test_weather_matches_web_search(self) -> None:
        results = match_skills_by_keywords("오늘 날씨 어때?")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("web_search", skill_ids)

    def test_browser_search_matches_browser_search(self) -> None:
        results = match_skills_by_keywords("구글에서 맥미니 MLX 성능 검색해줘")
        skill_ids = [s.skill_id for s, _ in results]
        self.assertIn("browser_search", skill_ids)

    def test_disabled_skill_not_matched(self) -> None:
        skill = get_skill_by_id("calendar_create")
        skill.enabled = False
        try:
            results = match_skills_by_keywords("내일 일정 추가해줘")
            matched_ids = [s.skill_id for s, _ in results]
            self.assertNotIn("calendar_create", matched_ids)
        finally:
            skill.enabled = True


class ClassifyIntentFromRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        _SKILL_REGISTRY.clear()
        ensure_initialized()

    def tearDown(self) -> None:
        _SKILL_REGISTRY.clear()

    def test_calendar_create_intent(self) -> None:
        result = classify_intent_from_registry("일정 추가해줘")
        self.assertEqual(result, "calendar_create")

    def test_calendar_delete_intent(self) -> None:
        result = classify_intent_from_registry("캘린더 일정 삭제해줘")
        self.assertEqual(result, "calendar_delete")

    def test_gmail_draft_intent(self) -> None:
        result = classify_intent_from_registry("gmail 초안 작성해줘")
        self.assertEqual(result, "gmail_draft")

    def test_ambiguous_mail_action_returns_none(self) -> None:
        result = classify_intent_from_registry(
            "보낸 사람 la9527@daum.net 제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘"
        )
        self.assertIsNone(result)

    def test_note_create_intent(self) -> None:
        result = classify_intent_from_registry("메모 작성해줘")
        self.assertEqual(result, "macos_note_create")

    def test_chat_returns_none(self) -> None:
        result = classify_intent_from_registry("안녕 오늘 기분이 좋아")
        self.assertIsNone(result)

    def test_weather_maps_to_web_search(self) -> None:
        result = classify_intent_from_registry("오늘 날씨 어때?")
        self.assertEqual(result, "web_search")


if __name__ == "__main__":
    unittest.main()
