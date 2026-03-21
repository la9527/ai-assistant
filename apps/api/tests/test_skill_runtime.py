import unittest
from unittest.mock import patch

from app.automation import _execute_registered_skill
from app.automation import extract_structured_request
from app.skills.registry import ensure_initialized
from app.skills.registry import get_skill_runtime


class SkillRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_initialized()

    def test_extract_structured_request_sets_skill_id_for_calendar(self) -> None:
        extraction = extract_structured_request("내일 오후 3시에 치과 일정 추가해줘", "test")
        self.assertEqual(extraction.intent, "calendar_create")
        self.assertEqual(extraction.skill_id, "calendar_create")
        self.assertEqual(extraction.domain, "calendar")

    def test_extract_structured_request_sets_browser_payload(self) -> None:
        extraction = extract_structured_request("https://example.com 읽어줘", "test")
        self.assertEqual(extraction.intent, "browser_read")
        self.assertEqual(extraction.domain, "browser")
        self.assertIsNotNone(extraction.browser)
        self.assertEqual(extraction.browser.url, "https://example.com")

    def test_extract_structured_request_sets_macos_payload(self) -> None:
        extraction = extract_structured_request("볼륨 50으로 설정해줘", "test")
        self.assertEqual(extraction.intent, "macos_volume_set")
        self.assertEqual(extraction.domain, "macos")
        self.assertIsNotNone(extraction.macos)
        self.assertEqual(extraction.macos.volume_level, 50)

    def test_mail_runtime_registered(self) -> None:
        runtime = get_skill_runtime("gmail_draft")
        self.assertIsNotNone(runtime)
        self.assertGreater(len(runtime.descriptor().intent_examples), 0)

    def test_registered_skill_returns_approval_before_execution(self) -> None:
        extraction = extract_structured_request(
            "test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘",
            "test",
        )
        result = _execute_registered_skill(
            extraction=extraction,
            message=extraction.raw_message,
            channel="web",
            session_id="session-1",
            user_id="user-1",
            approval_granted=False,
            memory_context=None,
            intent_override=None,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "gmail_draft")

    def test_registered_calendar_skill_executes_via_runtime(self) -> None:
        extraction = extract_structured_request("내일 오후 3시에 치과 일정 추가해줘", "test")
        with patch("app.automation.run_n8n_automation", return_value="일정 생성 완료"):
            result = _execute_registered_skill(
                extraction=extraction,
                message=extraction.raw_message,
                channel="web",
                session_id="session-1",
                user_id="user-1",
                approval_granted=True,
                memory_context=None,
                intent_override=None,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "n8n")
        self.assertEqual(result["reply"], "일정 생성 완료")

    def test_registered_macos_volume_get_executes_via_runtime(self) -> None:
        extraction = extract_structured_request("현재 볼륨 알려줘", "test")
        with patch("app.automation.run_macos_get", return_value="현재 볼륨은 35%입니다."):
            result = _execute_registered_skill(
                extraction=extraction,
                message=extraction.raw_message,
                channel="web",
                session_id="session-1",
                user_id="user-1",
                approval_granted=True,
                memory_context=None,
                intent_override=None,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "macos")
        self.assertEqual(result["reply"], "현재 볼륨은 35%입니다.")

    def test_registered_note_skill_requires_approval(self) -> None:
        extraction = extract_structured_request(
            "메모에 제목 주간 점검 내용 브라우저 러너 상태 확인 저장해줘",
            "test",
        )
        result = _execute_registered_skill(
            extraction=extraction,
            message=extraction.raw_message,
            channel="web",
            session_id="session-1",
            user_id="user-1",
            approval_granted=False,
            memory_context=None,
            intent_override=None,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "macos_note_create")

    def test_registered_browser_search_executes_via_runtime(self) -> None:
        extraction = extract_structured_request("구글에서 맥미니 MLX 성능 검색해줘", "test")
        browser_payload = {"items": [{"title": "MLX Bench", "url": "https://example.com/mlx"}]}
        with patch("app.skills.browser.implementation.httpx.Client") as mocked_client:
            mocked_response = mocked_client.return_value.__enter__.return_value.post.return_value
            mocked_response.raise_for_status.return_value = None
            mocked_response.json.return_value = browser_payload
            result = _execute_registered_skill(
                extraction=extraction,
                message=extraction.raw_message,
                channel="web",
                session_id="session-1",
                user_id="user-1",
                approval_granted=True,
                memory_context=None,
                intent_override=None,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "browser")
        self.assertIn("브라우저 검색을 완료했습니다.", result["reply"])


if __name__ == "__main__":
    unittest.main()