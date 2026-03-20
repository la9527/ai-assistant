"""LangGraph 워크플로 및 외부 LLM 라우팅 테스트.

langgraph가 설치되지 않은 환경에서는 legacy fallback 경로를 검증한다.
"""

import unittest
from unittest.mock import patch

from app.config import settings


class ProcessMessageFallbackTests(unittest.TestCase):
    """process_message가 LangGraph import 실패 시 legacy로 fallback하는지 검증."""

    @patch("app.automation.generate_local_reply", return_value=("테스트 응답", "local_llm"))
    def test_process_message_returns_reply(self, mock_llm):
        from app.automation import process_message
        result = process_message(
            message="안녕하세요",
            channel="test",
            session_id="test-session",
        )
        self.assertIn("reply", result)
        self.assertIn("route", result)
        self.assertIsNotNone(result["reply"])

    @patch("app.automation.generate_local_reply", return_value=("답변", "local_llm"))
    def test_chat_intent_returns_local_llm(self, mock_llm):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="날씨 어때?",
            channel="test",
            session_id="s1",
        )
        self.assertEqual(result["route"], "local_llm")

    def test_calendar_create_requires_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="내일 오후 3시에 치과 일정 추가해줘",
            channel="test",
            session_id="s1",
            approval_granted=False,
        )
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "calendar_create")

    def test_gmail_draft_requires_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="test@example.com로 제목 주간 보고 내용 완료 메일 초안 작성해줘",
            channel="test",
            session_id="s1",
            approval_granted=False,
        )
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "gmail_draft")

    def test_macos_note_requires_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="메모에 제목 테스트 내용 확인사항 저장해줘",
            channel="test",
            session_id="s1",
            approval_granted=False,
        )
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "macos_note_create")

    def test_calendar_missing_params_returns_validation_error(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="일정 추가해줘",
            channel="test",
            session_id="s1",
        )
        self.assertEqual(result["route"], "validation_error")

    def test_gmail_detail_without_context_returns_guidance(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="메일 자세히 보여줘",
            channel="test",
            session_id="s1",
        )
        self.assertEqual(result["route"], "validation_error")
        self.assertIn("같은 대화에서 먼저 메일 목록", result["reply"])


class MacOSNewIntentsTests(unittest.TestCase):
    """새 macOS 인텐트 분류 및 라우팅 검증."""

    def test_reminder_intent_classification(self):
        from app.automation import classify_message_intent
        self.assertEqual(classify_message_intent("미리알림에 장보기 추가해줘"), "macos_reminder_create")

    def test_reminder_requires_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="미리알림에 이름 장보기 추가해줘",
            channel="test",
            session_id="s1",
            approval_granted=False,
        )
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "macos_reminder_create")

    def test_volume_get_intent(self):
        from app.automation import classify_message_intent
        self.assertEqual(classify_message_intent("볼륨 확인해줘"), "macos_volume_get")

    def test_volume_set_intent(self):
        from app.automation import classify_message_intent
        self.assertEqual(classify_message_intent("볼륨 50으로 설정해줘"), "macos_volume_set")

    def test_volume_set_requires_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="볼륨 50으로 설정해줘",
            channel="test",
            session_id="s1",
            approval_granted=False,
        )
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "macos_volume_set")

    def test_volume_get_no_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="볼륨 확인해줘",
            channel="test",
            session_id="s1",
        )
        # volume_get은 승인 불필요; runner가 없으면 fallback
        self.assertIn(result["route"], ("macos", "macos_fallback"))
        self.assertEqual(result["action_type"], "macos_volume_get")

    def test_darkmode_intent(self):
        from app.automation import classify_message_intent
        self.assertEqual(classify_message_intent("다크모드 전환해줘"), "macos_darkmode_toggle")

    def test_darkmode_requires_approval(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="다크모드 전환해줘",
            channel="test",
            session_id="s1",
            approval_granted=False,
        )
        self.assertEqual(result["route"], "approval_required")
        self.assertEqual(result["action_type"], "macos_darkmode_toggle")

    def test_finder_intent(self):
        from app.automation import classify_message_intent
        self.assertEqual(classify_message_intent("파인더로 ~/Documents 폴더 열어줘"), "macos_finder_open")

    def test_finder_validation_error_no_path(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="파인더 열어줘",
            channel="test",
            session_id="s1",
        )
        self.assertEqual(result["route"], "validation_error")
        self.assertEqual(result["action_type"], "macos_finder_open")

    def test_finder_no_approval_required(self):
        from app.automation import _process_message_legacy
        result = _process_message_legacy(
            message="파인더로 ~/Documents 폴더 열어줘",
            channel="test",
            session_id="s1",
        )
        # finder_open은 승인 불필요; runner가 없으면 fallback
        self.assertIn(result["route"], ("macos", "macos_fallback"))
        self.assertEqual(result["action_type"], "macos_finder_open")


class MacOSParserTests(unittest.TestCase):
    """macOS 요청 파서 검증."""

    def test_parse_reminder_with_labels(self):
        from app.automation import parse_macos_reminder_request
        result = parse_macos_reminder_request("미리알림에 이름 장보기 메모 우유 사기 목록 개인 추가해줘")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "장보기")
        self.assertEqual(result["note"], "우유 사기")
        self.assertEqual(result["list_name"], "개인")

    def test_parse_reminder_without_labels(self):
        from app.automation import parse_macos_reminder_request
        result = parse_macos_reminder_request("미리알림에 장보기 추가해줘")
        self.assertIsNotNone(result)
        self.assertIn("장보기", result["name"])

    def test_parse_volume_set(self):
        from app.automation import parse_macos_volume_set_request
        result = parse_macos_volume_set_request("볼륨 75로 설정해줘")
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], 75)

    def test_parse_volume_set_invalid(self):
        from app.automation import parse_macos_volume_set_request
        result = parse_macos_volume_set_request("볼륨 200으로 설정해줘")
        self.assertIsNone(result)

    def test_parse_finder_path(self):
        from app.automation import parse_macos_finder_open_request
        result = parse_macos_finder_open_request("~/Documents 폴더 열어줘")
        self.assertIsNotNone(result)
        self.assertEqual(result["path"], "~/Documents")

    def test_parse_finder_rejects_traversal(self):
        from app.automation import parse_macos_finder_open_request
        result = parse_macos_finder_open_request("/tmp/../etc/passwd 폴더 열어줘")
        self.assertIsNone(result)


class ExternalLLMConfigTests(unittest.TestCase):
    """외부 LLM 설정이 올바르게 로드되는지 검증."""

    def test_external_llm_disabled_by_default(self):
        self.assertFalse(settings.external_llm.enabled)

    def test_external_llm_default_provider(self):
        self.assertEqual(settings.external_llm.provider, "openai")

    def test_external_llm_fallback_only_default(self):
        self.assertTrue(settings.external_llm.fallback_only)


class ExternalLLMReplyTests(unittest.TestCase):
    """generate_external_reply 기본 동작 검증."""

    def test_external_reply_returns_fallback_when_disabled(self):
        from app.llm import generate_external_reply
        reply, route = generate_external_reply("테스트", "test")
        self.assertEqual(route, "fallback")


if __name__ == "__main__":
    unittest.main()
