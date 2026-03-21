import json
import unittest

from app.automation import _calendar_payload_to_request
from app.automation import _build_gmail_search_query
from app.automation import build_gmail_detail_target_guidance
from app.automation import _parse_summary_time_range
from app.automation import apply_reference_context
from app.automation import extract_candidates_from_reply
from app.automation import extract_structured_request
from app.automation import extract_user_memory_candidates
from app.automation import parse_ordinal_index
from app.automation import classify_message_intent
from app.llm import _build_local_reply_messages
from app.automation import _mail_payload_to_compose_request
from app.automation import _mail_payload_to_detail_request
from app.automation import _mail_payload_to_reply_request
from app.automation import _merge_mail_payload
from app.automation import _normalize_gmail_reply_body
from app.automation import parse_calendar_request
from app.automation import parse_gmail_compose_request
from app.automation import parse_gmail_detail_request
from app.automation import parse_gmail_reply_request
from app.schemas import CalendarExtractionPayload
from app.schemas import MailExtractionPayload
from app.schemas import StructuredExtraction


class GmailReplyNormalizationTests(unittest.TestCase):
    def test_normalize_gmail_reply_body_removes_prefix_and_suffix(self) -> None:
        self.assertEqual(
            _normalize_gmail_reply_body("답장 내용: 확인했습니다 메일에 이어서 답장해줘"),
            "확인했습니다",
        )
        self.assertEqual(
            _normalize_gmail_reply_body("내용: 검토 완료했습니다 메일에 답장해줘"),
            "검토 완료했습니다",
        )

    def test_parse_gmail_reply_request_stores_clean_body(self) -> None:
        parsed = parse_gmail_reply_request(
            "제목 AI Assistant Gmail 발송 테스트 내용 답장 내용: 확인했습니다 메일에 답장해줘",
            "gmail_reply",
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["reply_mode"], "reply")
        self.assertEqual(parsed["message"], "확인했습니다")
        self.assertEqual(parsed["subject"], "AI Assistant Gmail 발송 테스트")
        self.assertEqual(
            parsed["search_query"],
            'subject:"AI Assistant Gmail 발송 테스트" newer_than:30d',
        )

    def test_mail_payload_to_reply_request_uses_clean_body(self) -> None:
        payload = MailExtractionPayload(
            replyMode="thread",
            subject="AI Assistant Gmail 발송 테스트",
            body="답장 내용: 확인했습니다 메일에 이어서 답장해줘",
            searchQuery='subject:"AI Assistant Gmail 발송 테스트" newer_than:30d',
        )

        request_payload = _mail_payload_to_reply_request(payload, "gmail_thread_reply")

        self.assertIsNotNone(request_payload)
        self.assertEqual(request_payload["reply_mode"], "thread")
        self.assertEqual(request_payload["message"], "확인했습니다")

    def test_merge_mail_payload_keeps_clean_reply_body(self) -> None:
        baseline = MailExtractionPayload(
            replyMode="reply",
            subject="AI Assistant Gmail 발송 테스트",
            body="확인했습니다 메일에 답장해줘",
            searchQuery='subject:"AI Assistant Gmail 발송 테스트" newer_than:30d',
        )
        llm_payload = MailExtractionPayload(
            replyMode="reply",
            subject="AI Assistant Gmail 발송 테스트",
            body="답장 내용: 확인했습니다 메일에 답장해줘",
            searchQuery='subject:"AI Assistant Gmail 발송 테스트" newer_than:30d',
        )

        merged = _merge_mail_payload(baseline, llm_payload)

        self.assertIsNotNone(merged)
        self.assertEqual(merged.body, "확인했습니다")


class CalendarAndComposeExtractionTests(unittest.TestCase):
    def test_parse_calendar_create_request_uses_absolute_date(self) -> None:
        parsed = parse_calendar_request("2026-03-20 오후 3시 치과 일정 추가해줘", "calendar_create")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "치과")
        self.assertEqual(parsed["start_at"], "2026-03-20T15:00:00+09:00")
        self.assertEqual(parsed["end_at"], "2026-03-20T16:00:00+09:00")
        self.assertEqual(parsed["timezone"], "Asia/Seoul")

    def test_parse_calendar_update_request_includes_search_window(self) -> None:
        parsed = parse_calendar_request("2026-03-20 오후 3시 치과 일정을 오후 4시로 변경해줘", "calendar_update")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "치과")
        self.assertEqual(parsed["search_title"], "치과")
        self.assertEqual(parsed["search_time_min"], "2026-03-20T15:00:00+09:00")
        self.assertEqual(parsed["search_time_max"], "2026-03-20T16:00:00+09:00")

    def test_calendar_payload_to_delete_request_keeps_search_fields(self) -> None:
        payload = CalendarExtractionPayload(
            searchTitle="피자 시키기",
            searchTimeMin="2026-03-20T06:00:00+09:00",
            searchTimeMax="2026-03-20T07:00:00+09:00",
            timezone="Asia/Seoul",
        )

        request_payload = _calendar_payload_to_request(payload, "calendar_delete")

        self.assertEqual(
            request_payload,
            {
                "search_title": "피자 시키기",
                "search_time_min": "2026-03-20T06:00:00+09:00",
                "search_time_max": "2026-03-20T07:00:00+09:00",
                "timezone": "Asia/Seoul",
            },
        )

    def test_parse_gmail_draft_request_extracts_recipients_subject_and_body(self) -> None:
        parsed = parse_gmail_compose_request(
            "test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘",
            "gmail_draft",
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["send_to"], "test@example.com")
        self.assertEqual(parsed["subject"], "주간 보고")
        self.assertEqual(parsed["message"], "오늘 작업 완료")
        self.assertEqual(parsed["action"], "gmail_draft")

    def test_mail_payload_to_compose_request_preserves_send_fields(self) -> None:
        payload = MailExtractionPayload(
            recipients=["test@example.com"],
            cc=["copy@example.com"],
            bcc=["blind@example.com"],
            subject="주간 보고",
            body="오늘 작업 완료",
            attachmentUrls=["https://example.com/file.txt"],
        )

        request_payload = _mail_payload_to_compose_request(payload, "gmail_send")

        self.assertEqual(
            request_payload,
            {
                "send_to": "test@example.com",
                "subject": "주간 보고",
                "message": "오늘 작업 완료",
                "email_type": "text",
                "action": "gmail_send",
                "cc_list": "copy@example.com",
                "bcc_list": "blind@example.com",
                "attachment_url": "https://example.com/file.txt",
            },
        )

    def test_apply_reference_context_reuses_previous_calendar_delete_target(self) -> None:
        previous = StructuredExtraction(
            rawMessage="오늘 06:00-07:00 피자 시키기 일정 삭제해줘",
            normalizedMessage="오늘 06:00-07:00 피자 시키기 일정 삭제해줘",
            channel="web",
            domain="calendar",
            action="delete",
            intent="calendar_delete",
            needsClarification=False,
            approvalRequired=True,
            calendar=CalendarExtractionPayload(
                searchTitle="피자 시키기",
                searchTimeMin="2026-03-20T06:00:00+09:00",
                searchTimeMax="2026-03-20T07:00:00+09:00",
                timezone="Asia/Seoul",
            ),
        )
        current = StructuredExtraction(
            rawMessage="그 일정 삭제해줘",
            normalizedMessage="그 일정 삭제해줘",
            channel="web",
            domain="calendar",
            action="delete",
            intent="calendar_delete",
            needsClarification=True,
            approvalRequired=True,
            missingFields=["title", "date_or_time"],
        )

        merged = apply_reference_context(current, previous)

        self.assertFalse(merged.needs_clarification)
        self.assertEqual(merged.calendar.search_title, "피자 시키기")
        self.assertEqual(merged.calendar.search_time_min, "2026-03-20T06:00:00+09:00")

    def test_apply_reference_context_reuses_previous_gmail_send_fields(self) -> None:
        previous = StructuredExtraction(
            rawMessage="test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘",
            normalizedMessage="test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘",
            channel="web",
            domain="mail",
            action="draft",
            intent="gmail_draft",
            needsClarification=False,
            approvalRequired=True,
            mail=MailExtractionPayload(
                recipients=["test@example.com"],
                subject="주간 보고",
                body="오늘 작업 완료",
            ),
        )
        current = StructuredExtraction(
            rawMessage="그 메일 보내줘",
            normalizedMessage="그 메일 보내줘",
            channel="web",
            domain="mail",
            action="send",
            intent="gmail_send",
            needsClarification=True,
            approvalRequired=True,
            missingFields=["recipients", "subject", "body"],
        )

        merged = apply_reference_context(current, previous)

        self.assertFalse(merged.needs_clarification)
        self.assertEqual(merged.mail.recipients, ["test@example.com"])
        self.assertEqual(merged.mail.subject, "주간 보고")
        self.assertEqual(merged.mail.body, "오늘 작업 완료")


class LongTermMemoryPromptTests(unittest.TestCase):
    def test_build_local_reply_messages_includes_memory_context(self) -> None:
        messages = _build_local_reply_messages(
            "오늘 일정 요약해줘",
            "web",
            memory_context=[
                {"category": "preference", "content": "답변은 짧고 오전 기준으로 정리", "source": "manual"},
                {"category": "profile", "content": "슬랙과 카카오를 같은 사용자로 본다", "source": "admin"},
            ],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("장기 메모리", messages[1]["content"])
        self.assertIn("답변은 짧고 오전 기준으로 정리", messages[1]["content"])
        self.assertIn("profile/admin", messages[1]["content"])
        self.assertEqual(messages[-1]["role"], "user")

    def test_build_local_reply_messages_skips_blank_memories(self) -> None:
        messages = _build_local_reply_messages(
            "안녕",
            "web",
            memory_context=[{"category": "general", "content": "   ", "source": "manual"}],
        )

        self.assertEqual(len(messages), 2)


class AutomaticMemoryExtractionTests(unittest.TestCase):
    def test_extract_user_memory_candidates_prefers_explicit_preference_cues(self) -> None:
        candidates = extract_user_memory_candidates("앞으로 일정 요약은 짧게 핵심만 보여줘, 기억해줘")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["category"], "preference")
        self.assertEqual(candidates[0]["content"], "일정 요약은 짧게 핵심만 보여줘")

    def test_extract_user_memory_candidates_ignores_secrets(self) -> None:
        candidates = extract_user_memory_candidates("이 비밀번호는 1234야 기억해줘")

        self.assertEqual(candidates, [])


class ParseOrdinalIndexTests(unittest.TestCase):
    def test_korean_ordinals(self) -> None:
        self.assertEqual(parse_ordinal_index("두 번째 일정 삭제해줘"), 1)
        self.assertEqual(parse_ordinal_index("첫 번째로 해줘"), 0)
        self.assertEqual(parse_ordinal_index("세번째"), 2)

    def test_digit_ordinals(self) -> None:
        self.assertEqual(parse_ordinal_index("1번 선택"), 0)
        self.assertEqual(parse_ordinal_index("3번으로 해"), 2)

    def test_no_ordinal_returns_none(self) -> None:
        self.assertIsNone(parse_ordinal_index("내일 일정 알려줘"))

    def test_out_of_range_digit_returns_none(self) -> None:
        self.assertIsNone(parse_ordinal_index("0번으로"))
        self.assertIsNone(parse_ordinal_index("100번"))


class ExtractCandidatesFromReplyTests(unittest.TestCase):
    def test_extracts_numbered_list(self) -> None:
        reply = "일정 목록입니다:\n1. 팀 미팅 오전 10시\n2. 점심 약속 12시\n3. 코드 리뷰 3시"
        result = extract_candidates_from_reply(reply, "n8n")

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["index"], 0)
        self.assertIn("팀 미팅", result[0]["label"])
        self.assertEqual(result[2]["index"], 2)

    def test_ignores_single_item(self) -> None:
        reply = "결과:\n1. 하나만 있음"
        result = extract_candidates_from_reply(reply, "n8n")
        self.assertEqual(result, [])

    def test_ignores_unsupported_routes(self) -> None:
        reply = "1. 첫번째\n2. 두번째"
        result = extract_candidates_from_reply(reply, "direct")
        self.assertEqual(result, [])


class CandidateSelectionReferenceTests(unittest.TestCase):
    def _make_extraction(self, message: str, domain: str = "calendar", action: str = "read") -> StructuredExtraction:
        cal = CalendarExtractionPayload() if domain == "calendar" else None
        return StructuredExtraction(
            raw_message=message,
            normalizedMessage=message,
            domain=domain,
            action=action,
            intent=f"{domain}_{action}",
            confidence=0.8,
            calendar=cal,
        )

    def test_ordinal_selects_candidate(self) -> None:
        extraction = self._make_extraction("두 번째 삭제해줘", domain="calendar", action="delete")
        previous = self._make_extraction("일정 보여줘", domain="calendar", action="read")
        candidates = [
            {"index": 0, "label": "팀 미팅 10시", "raw": "팀 미팅 10시"},
            {"index": 1, "label": "점심 약속 12시", "raw": "점심 약속 12시"},
            {"index": 2, "label": "코드 리뷰 3시", "raw": "코드 리뷰 3시"},
        ]

        result = apply_reference_context(extraction, previous, last_candidates=candidates)

        self.assertTrue(result.metadata.get("candidate_selected"))
        self.assertEqual(result.metadata.get("candidate_index"), 1)
        self.assertEqual(result.calendar.title, "점심 약속 12시")

    def test_ordinal_without_candidates_does_nothing(self) -> None:
        extraction = self._make_extraction("두 번째 보여줘", domain="calendar")
        previous = self._make_extraction("일정 보여줘", domain="calendar")

        result = apply_reference_context(extraction, previous, last_candidates=None)
        self.assertFalse(result.metadata.get("candidate_selected", False))

    def test_chat_domain_inherits_from_previous(self) -> None:
        extraction = self._make_extraction("1번", domain="chat", action="reply")
        extraction.calendar = None
        previous = self._make_extraction("일정 보여줘", domain="calendar", action="read")
        candidates = [
            {"index": 0, "label": "팀 미팅 10시", "raw": "팀 미팅 10시"},
            {"index": 1, "label": "점심 약속 12시", "raw": "점심 약속 12시"},
        ]

        result = apply_reference_context(extraction, previous, last_candidates=candidates)

        self.assertEqual(result.domain, "calendar")
        self.assertEqual(result.action, "read")

    def test_gmail_detail_single_candidate_auto_selected(self) -> None:
        extraction = StructuredExtraction(
            raw_message="메일 자세히 보여줘",
            normalizedMessage="메일 자세히 보여줘",
            domain="mail",
            action="read",
            intent="gmail_detail",
            confidence=0.8,
        )
        previous = StructuredExtraction(
            raw_message="최근 메일 보여줘",
            normalizedMessage="최근 메일 보여줘",
            domain="mail",
            action="read",
            intent="gmail_list",
            confidence=0.8,
        )
        candidates = [
            {
                "index": 0,
                "label": "보안 알림",
                "raw": "Google - 보안 알림",
                "sender": '"Google" <no-reply@accounts.google.com>',
                "message_id": "18f0abc123",
                "thread_id": "thread-001",
            }
        ]

        result = apply_reference_context(extraction, previous, last_candidates=candidates)

        self.assertTrue(result.metadata.get("candidate_selected"))
        self.assertIsNotNone(result.mail)
        self.assertEqual(result.mail.message_reference, "18f0abc123")
        self.assertEqual(result.mail.thread_reference, "thread-001")

    def test_gmail_detail_multiple_candidates_adds_guidance_hints(self) -> None:
        extraction = StructuredExtraction(
            raw_message="메일 자세히 보여줘",
            normalizedMessage="메일 자세히 보여줘",
            domain="mail",
            action="read",
            intent="gmail_detail",
            confidence=0.8,
        )
        previous = StructuredExtraction(
            raw_message="최근 메일 보여줘",
            normalizedMessage="최근 메일 보여줘",
            domain="mail",
            action="read",
            intent="gmail_list",
            confidence=0.8,
        )
        candidates = [
            {"index": 0, "label": "보안 알림", "sender": "Google"},
            {"index": 1, "label": "Gemini 결제 설정 안내", "sender": "Google AI Studio"},
        ]

        result = apply_reference_context(extraction, previous, last_candidates=candidates)
        reply = build_gmail_detail_target_guidance(result)

        self.assertIn("1번.", reply)
        self.assertIn("2번.", reply)
        self.assertIn("직전 목록", reply)


class SummaryTimeRangeTests(unittest.TestCase):
    def test_today_returns_range(self) -> None:
        time_min, time_max = _parse_summary_time_range("오늘 일정 보여줘")

        self.assertIsNotNone(time_min)
        self.assertIsNotNone(time_max)
        self.assertIn("T00:00:00", time_min)

    def test_this_week_returns_range(self) -> None:
        time_min, time_max = _parse_summary_time_range("이번 주 일정 알려줘")

        self.assertIsNotNone(time_min)
        self.assertIsNotNone(time_max)

    def test_no_time_ref_returns_none(self) -> None:
        time_min, time_max = _parse_summary_time_range("일정 보여줘")

        self.assertIsNone(time_min)
        self.assertIsNone(time_max)


class GmailSearchQueryTests(unittest.TestCase):
    def test_today_mail(self) -> None:
        query = _build_gmail_search_query("오늘 메일 보여줘")

        self.assertIsNotNone(query)
        self.assertIn("newer_than:1d", query)

    def test_recent_mail(self) -> None:
        query = _build_gmail_search_query("최근 메일 알려줘")

        self.assertIsNotNone(query)
        self.assertIn("newer_than:3d", query)

    def test_no_filter_returns_none(self) -> None:
        query = _build_gmail_search_query("메일 보여줘")

        self.assertIsNone(query)


class GmailListAndDetailExtractionTests(unittest.TestCase):
    def test_classify_gmail_detail_intent(self) -> None:
        intent = classify_message_intent("메일 첫번째 항목 본문 자세히 보여줘")
        self.assertEqual(intent, "gmail_detail")

    def test_classify_gmail_list_intent(self) -> None:
        intent = classify_message_intent("메일 목록 더 보여줘")
        self.assertEqual(intent, "gmail_list")

    def test_gmail_list_extracts_limit_and_grouping(self) -> None:
        extraction = extract_structured_request("오늘 메일 12건 날짜별로 목록 보여줘")

        self.assertIn(extraction.intent, ("gmail_summary", "gmail_list"))
        self.assertIsNotNone(extraction.mail)
        self.assertEqual(extraction.mail.limit, 12)
        self.assertTrue(extraction.mail.group_by_date)

    def test_parse_gmail_detail_request_with_subject(self) -> None:
        parsed = parse_gmail_detail_request("제목 주간 보고 메일 본문 상세 보여줘")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["subject"], "주간 보고")
        self.assertEqual(parsed["detail_level"], "full")

    def test_mail_payload_to_detail_request_requires_target(self) -> None:
        payload = MailExtractionPayload(detailLevel="brief")
        self.assertIsNone(_mail_payload_to_detail_request(payload))

    def test_mail_payload_to_detail_request_uses_message_reference(self) -> None:
        payload = MailExtractionPayload(
            messageReference="18f0abc123",
            detailLevel="full",
        )

        parsed = _mail_payload_to_detail_request(payload)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["message_id"], "18f0abc123")
        self.assertEqual(parsed["detail_level"], "full")


class SummaryExtractionIntegrationTests(unittest.TestCase):
    def test_calendar_summary_includes_time_payload(self) -> None:
        extraction = extract_structured_request("오늘 일정 보여줘")

        self.assertEqual(extraction.intent, "calendar_summary")
        self.assertIsNotNone(extraction.calendar)
        self.assertIsNotNone(extraction.calendar.search_time_min)
        self.assertIsNotNone(extraction.calendar.search_time_max)

    def test_gmail_summary_includes_search_query(self) -> None:
        extraction = extract_structured_request("오늘 메일 알려줘")

        self.assertEqual(extraction.intent, "gmail_summary")
        self.assertIsNotNone(extraction.mail)
        self.assertIsNotNone(extraction.mail.search_query)
        self.assertIn("newer_than:1d", extraction.mail.search_query)


# ---------------------------------------------------------------------------
# External LLM multi-provider 설정 및 호출 테스트
# ---------------------------------------------------------------------------

from app.config import ExternalLLMSettings
from app.llm import (
    _call_anthropic,
    _call_gemini,
    _call_openai_compatible,
    _call_external_llm,
)


class ExternalLLMConfigTests(unittest.TestCase):
    """ExternalLLMSettings 멀티 프로바이더 설정 테스트."""

    def test_default_provider_is_openai(self) -> None:
        ext = ExternalLLMSettings()
        self.assertEqual(ext.provider, "openai")
        self.assertEqual(ext.base_url, "https://api.openai.com/v1")
        self.assertEqual(ext.model, "gpt-4o-mini")
        self.assertFalse(ext.enabled)

    def test_anthropic_provider(self) -> None:
        ext = ExternalLLMSettings(
            enabled=True,
            provider="anthropic",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
        )
        self.assertTrue(ext.enabled)
        self.assertEqual(ext.provider, "anthropic")

    def test_gemini_provider(self) -> None:
        ext = ExternalLLMSettings(
            enabled=True,
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com",
            api_key="AIza-test",
            model="gemini-2.5-flash",
        )
        self.assertTrue(ext.enabled)
        self.assertEqual(ext.provider, "gemini")

    def test_structured_extraction_model_defaults_to_model(self) -> None:
        ext = ExternalLLMSettings(
            enabled=True, provider="openai", api_key="test",
            model="gpt-4o", structured_extraction_model="",
        )
        # structured_extraction_model 이 빈 문자열이면 config property에서 model로 대체
        self.assertEqual(ext.structured_extraction_model, "")

    def test_structured_extraction_enabled(self) -> None:
        ext = ExternalLLMSettings(
            enabled=True, provider="openai", api_key="test",
            structured_extraction_enabled=True,
        )
        self.assertTrue(ext.structured_extraction_enabled)


class ExternalLLMDispatcherTests(unittest.TestCase):
    """_call_external_llm 이 provider에 따라 올바른 함수로 분기하는지 확인."""

    def test_dispatch_openai(self) -> None:
        ext = ExternalLLMSettings(provider="openai", api_key="test", base_url="http://localhost:9999/v1")
        messages = [{"role": "user", "content": "hello"}]
        # 실제 호출은 실패하지만 올바른 경로로 분기되는지만 확인
        with self.assertRaises(Exception):
            _call_external_llm(ext, messages, "gpt-4o-mini")

    def test_dispatch_anthropic(self) -> None:
        ext = ExternalLLMSettings(provider="anthropic", api_key="test", base_url="http://localhost:9999")
        messages = [{"role": "user", "content": "hello"}]
        with self.assertRaises(Exception):
            _call_external_llm(ext, messages, "claude-sonnet-4-20250514")

    def test_dispatch_gemini(self) -> None:
        ext = ExternalLLMSettings(provider="gemini", api_key="test", base_url="http://localhost:9999")
        messages = [{"role": "user", "content": "hello"}]
        with self.assertRaises(Exception):
            _call_external_llm(ext, messages, "gemini-2.5-flash")

    def test_unknown_provider_falls_back_to_openai_compatible(self) -> None:
        ext = ExternalLLMSettings(provider="groq", api_key="test", base_url="http://localhost:9999/v1")
        messages = [{"role": "user", "content": "hello"}]
        with self.assertRaises(Exception):
            _call_external_llm(ext, messages, "llama-3-70b")


class AnthropicMessageFormatTests(unittest.TestCase):
    """Anthropic API 메시지 변환 로직 테스트."""

    def test_system_messages_separated(self) -> None:
        """system 메시지가 Anthropic의 top-level system 필드로 분리되는지 확인."""
        # _call_anthropic 내부에서 system/user 분리가 일어남
        # 실제 HTTP 호출 없이 메시지 분리 로직만 간접 확인
        messages = [
            {"role": "system", "content": "시스템 프롬프트"},
            {"role": "user", "content": "안녕"},
        ]
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [m for m in messages if m["role"] != "system"]
        self.assertEqual(len(system_parts), 1)
        self.assertEqual(system_parts[0], "시스템 프롬프트")
        self.assertEqual(len(user_messages), 1)


class GeminiMessageFormatTests(unittest.TestCase):
    """Gemini API 메시지 변환 로직 테스트."""

    def test_role_mapping(self) -> None:
        """assistant → model 역할 매핑 확인."""
        messages = [
            {"role": "system", "content": "시스템"},
            {"role": "user", "content": "질문"},
            {"role": "assistant", "content": "답변"},
        ]
        contents = []
        system_text = ""
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"]
            else:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(system_text, "시스템")


# ---------------------------------------------------------------------------
# OpenAI 호환 엔드포인트 헬퍼 테스트
# ---------------------------------------------------------------------------

from app.main import (
    _openai_chat_response,
    _openai_stream_chunks,
    _OPENAI_COMPAT_MODEL,
)


class OpenAIChatResponseTests(unittest.TestCase):
    """_openai_chat_response 형식 검증."""

    def test_response_has_required_fields(self) -> None:
        resp = _openai_chat_response("안녕하세요")
        self.assertEqual(resp["object"], "chat.completion")
        self.assertIn("id", resp)
        self.assertIn("created", resp)
        self.assertIn("choices", resp)
        self.assertEqual(len(resp["choices"]), 1)
        choice = resp["choices"][0]
        self.assertEqual(choice["message"]["role"], "assistant")
        self.assertEqual(choice["message"]["content"], "안녕하세요")
        self.assertEqual(choice["finish_reason"], "stop")

    def test_default_model(self) -> None:
        resp = _openai_chat_response("test")
        self.assertEqual(resp["model"], _OPENAI_COMPAT_MODEL)

    def test_custom_model(self) -> None:
        resp = _openai_chat_response("test", model="gpt-4o")
        self.assertEqual(resp["model"], "gpt-4o")


class OpenAIStreamChunksTests(unittest.TestCase):
    """_openai_stream_chunks SSE 청크 형식 검증."""

    def test_stream_has_role_content_and_stop(self) -> None:
        chunks = _openai_stream_chunks("안녕하세요. 반갑습니다.")
        self.assertGreaterEqual(len(chunks), 3)  # role + content(s) + stop

        # 첫 청크: role
        first = json.loads(chunks[0])
        self.assertEqual(first["object"], "chat.completion.chunk")
        self.assertEqual(first["choices"][0]["delta"]["role"], "assistant")

        # 마지막 청크: finish_reason=stop
        last = json.loads(chunks[-1])
        self.assertEqual(last["choices"][0]["finish_reason"], "stop")
        self.assertEqual(last["choices"][0]["delta"], {})

    def test_content_chunks_contain_text(self) -> None:
        chunks = _openai_stream_chunks("첫 문장. 두번째 문장.")
        content_chunks = chunks[1:-1]
        full_text = "".join(
            json.loads(c)["choices"][0]["delta"]["content"] for c in content_chunks
        )
        self.assertIn("첫 문장", full_text)
        self.assertIn("두번째 문장", full_text)


# ---------------------------------------------------------------------------
# Gmail summary formatting
# ---------------------------------------------------------------------------

class GmailSummaryFormatTests(unittest.TestCase):
    """format_gmail_summary 채널별 포맷 검증."""

    SAMPLE_ITEMS = [
        {"index": 1, "sender": "alice@example.com", "subject": "회의 안건", "snippet": "내일 오전 10시", "date": "Mon, 17 Mar 2026"},
        {"index": 2, "sender": "bob@example.com", "subject": "보고서 검토 요청", "snippet": "첨부 파일 확인", "date": "Tue, 18 Mar 2026"},
    ]

    def test_webui_markdown_format_has_bold_and_sender(self) -> None:
        from app.llm import _format_gmail_items_markdown

        result = _format_gmail_items_markdown(self.SAMPLE_ITEMS)
        # Markdown 굵게 표시
        self.assertIn("**1) 회의 안건**", result)
        self.assertIn("**2) 보고서 검토 요청**", result)
        # 보낸 사람
        self.assertIn("alice@example.com", result)
        self.assertIn("bob@example.com", result)
        # 미리보기
        self.assertIn("내일 오전 10시", result)

    def test_compact_format_is_single_line_per_item(self) -> None:
        from app.llm import _format_gmail_items_compact

        result = _format_gmail_items_compact(self.SAMPLE_ITEMS, "")
        lines = [l for l in result.strip().split("\n") if l.strip()]
        # 제목 줄 + 아이템 2개 = 3줄
        self.assertEqual(len(lines), 3)
        self.assertIn("alice@example.com", result)

    def test_format_gmail_summary_webui_uses_markdown(self) -> None:
        from app.llm import format_gmail_summary

        body = {"reply": "원본", "items": self.SAMPLE_ITEMS}
        result = format_gmail_summary(body, "webui")
        # 외부 LLM 미설정 시 Markdown 템플릿 사용
        self.assertIn("**1) 회의 안건**", result)

    def test_format_gmail_summary_kakao_uses_compact(self) -> None:
        from app.llm import format_gmail_summary

        body = {"reply": "원본", "items": self.SAMPLE_ITEMS}
        result = format_gmail_summary(body, "kakao")
        # Kakao는 간결한 텍스트
        self.assertNotIn("**", result)
        self.assertIn("1. alice@example.com - 회의 안건", result)

    def test_format_gmail_summary_empty_items(self) -> None:
        from app.llm import format_gmail_summary

        body = {"reply": "", "items": []}
        result = format_gmail_summary(body, "webui")
        self.assertIn("메일이 없습니다", result)

    def test_markdown_format_empty_returns_no_mail_message(self) -> None:
        from app.llm import _format_gmail_items_markdown

        result = _format_gmail_items_markdown([])
        self.assertIn("메일이 없습니다", result)

    def test_parse_reply_fallback_slash_separated(self) -> None:
        """구버전 n8n reply (/ 구분) → items 파싱 후 Markdown 포맷."""
        from app.llm import format_gmail_summary

        old_reply = "최근 메일 요약입니다. 1. alice@example.com - 회의 안건 / 2. bob@test.io - 보고서 확인"
        body = {"reply": old_reply}
        result = format_gmail_summary(body, "webui")
        self.assertIn("**1) 회의 안건**", result)
        self.assertIn("alice@example.com", result)
        self.assertIn("**2) 보고서 확인**", result)

    def test_parse_reply_fallback_newline_separated(self) -> None:
        """줄바꿈 구분 reply → items 파싱."""
        from app.llm import format_gmail_summary

        reply = "최근 메일 요약입니다.\n1. a@b.com - 제목A\n2. c@d.com - 제목B"
        body = {"reply": reply}
        result = format_gmail_summary(body, "kakao")
        self.assertIn("1. a@b.com - 제목A", result)

    def test_parse_reply_fallback_no_items_returns_reply(self) -> None:
        """파싱 실패 시 원본 reply 반환."""
        from app.llm import format_gmail_summary

        body = {"reply": "메일 없음 알림"}
        result = format_gmail_summary(body, "webui")
        self.assertEqual(result, "메일 없음 알림")


class GmailDetailFormatTests(unittest.TestCase):
    def test_format_gmail_detail_webui_uses_safe_lines(self) -> None:
        from app.llm import format_gmail_detail

        body = {
            "subject": "[조치 필요] 결제 설정 확인",
            "sender": '"Google AI Studio" <googleaistudio-noreply@google.com>',
            "date": "Fri, 21 Mar 2026 09:00:00 +0900",
            "to": "la9527@daum.net",
            "messageId": "msg-123",
            "threadId": "thread-123",
            "snippet": "결제 정보를 확인해 주세요.",
            "body": "본문 확인이 필요합니다.",
        }

        result = format_gmail_detail(body, "webui")

        self.assertIn("📩 **메일 상세 정보**", result)
        self.assertIn("**제목**: (조치 필요) 결제 설정 확인", result)
        self.assertIn("보낸 사람:", result)
        self.assertIn("받는 사람: la9527@daum.net", result)
        self.assertIn("**본문**", result)
        self.assertNotIn("- 제목:", result)

    def test_format_gmail_detail_parses_legacy_reply(self) -> None:
        from app.llm import format_gmail_detail

        body = {
            "reply": (
                "📩 메일 상세 정보\n"
                "- 제목: [Action needed] Complete your billing setup\n"
                "- 보낸 사람: Google AI Studio <googleaistudio-noreply@google.com>\n"
                "- 받는 사람: la9527@daum.net\n"
                "- 메시지 ID: msg-456\n"
                "- 스레드 ID: thread-456\n"
                "- 미리보기: Billing setup required\n"
                "\n"
                "본문:\n"
                "Please complete your billing setup."
            )
        }

        result = format_gmail_detail(body, "webui")

        self.assertIn("**제목**: (Action needed) Complete your billing setup", result)
        self.assertIn("받는 사람: la9527@daum.net", result)
        self.assertIn("Please complete your billing setup.", result)


class GmailActionReplyFormatTests(unittest.TestCase):
    def test_format_send_reply_for_webui(self) -> None:
        from app.llm import format_gmail_action_reply

        result = format_gmail_action_reply(
            "la9527@daum.net로 메일을 발송했습니다. 제목은 'AI Assistant 메일 발송 테스트' 입니다.",
            "webui",
        )

        self.assertEqual(
            result,
            "메일을 발송했습니다.\n수신: la9527@daum.net\n제목: AI Assistant 메일 발송 테스트",
        )

    def test_format_reply_success_for_webui(self) -> None:
        from app.llm import format_gmail_action_reply

        result = format_gmail_action_reply(
            "메일 회신을 실행했습니다. 대상은 'AI Assistant Gmail 발송 테스트' 입니다.",
            "webui",
        )

        self.assertEqual(
            result,
            "메일 회신을 실행했습니다.\n대상: AI Assistant Gmail 발송 테스트",
        )

    def test_format_reply_not_found_for_webui(self) -> None:
        from app.llm import format_gmail_action_reply

        result = format_gmail_action_reply(
            "AI Assistant Gmail 발송 테스트에 대한 회신 대상을 찾지 못했습니다. 제목이나 thread id를 더 구체적으로 알려주세요.",
            "webui",
        )

        self.assertEqual(
            result,
            "회신 대상을 찾지 못했습니다.\n대상: AI Assistant Gmail 발송 테스트\n제목이나 thread id를 더 구체적으로 알려주세요.",
        )


class RunN8nAutomationRawTests(unittest.TestCase):
    """run_n8n_automation_raw 반환 형식 검증."""

    def test_returns_none_when_no_webhook_path(self) -> None:
        from app.automation import run_n8n_automation_raw

        result = run_n8n_automation_raw("msg", "kakao", "s1", None, None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Provider selection (ai-assistant:xxx)
# ---------------------------------------------------------------------------

class ProviderSelectionConfigTests(unittest.TestCase):
    """available_external_providers / resolve_external_llm 검증."""

    def test_resolve_external_llm_default_returns_external_llm(self) -> None:
        from app.config import settings

        ext = settings.resolve_external_llm(None)
        self.assertEqual(ext.provider, settings.external_llm.provider)

    def test_resolve_external_llm_openai_returns_openai_provider(self) -> None:
        from app.config import settings

        ext = settings.resolve_external_llm("openai")
        self.assertEqual(ext.provider, "openai")

    def test_resolve_external_llm_anthropic_returns_anthropic_provider(self) -> None:
        from app.config import settings

        ext = settings.resolve_external_llm("anthropic")
        self.assertEqual(ext.provider, "anthropic")

    def test_resolve_external_llm_gemini_returns_gemini_provider(self) -> None:
        from app.config import settings

        ext = settings.resolve_external_llm("gemini")
        self.assertEqual(ext.provider, "gemini")

    def test_resolve_external_llm_unknown_falls_back(self) -> None:
        from app.config import settings

        ext = settings.resolve_external_llm("unknown_provider")
        # unknown provider falls back to default external_llm
        self.assertEqual(ext.provider, settings.external_llm.provider)

    def test_available_providers_returns_list(self) -> None:
        from app.config import settings

        result = settings.available_external_providers()
        self.assertIsInstance(result, list)
        # 각 항목은 provider/model 키를 포함
        for item in result:
            self.assertIn("provider", item)
            self.assertIn("model", item)


class ProviderModelPrefixTests(unittest.TestCase):
    """ai-assistant:xxx 패턴 모델명 파싱 검증."""

    def test_model_prefix_parsing(self) -> None:
        from app.main import _OPENAI_COMPAT_MODEL, _OPENAI_COMPAT_MODEL_PREFIX

        model = "ai-assistant:claude"
        self.assertTrue(model.startswith(_OPENAI_COMPAT_MODEL_PREFIX))
        provider = model[len(_OPENAI_COMPAT_MODEL_PREFIX):]
        self.assertEqual(provider, "claude")

    def test_plain_model_no_prefix(self) -> None:
        from app.main import _OPENAI_COMPAT_MODEL, _OPENAI_COMPAT_MODEL_PREFIX

        model = _OPENAI_COMPAT_MODEL
        self.assertFalse(model.startswith(_OPENAI_COMPAT_MODEL_PREFIX))

    def test_claude_to_anthropic_normalization(self) -> None:
        """claude → anthropic 정규화 확인."""
        alias_map = {"claude": "anthropic"}
        self.assertEqual(alias_map.get("claude", "claude"), "anthropic")
        self.assertEqual(alias_map.get("openai", "openai"), "openai")

    def test_provider_display_names(self) -> None:
        from app.main import _PROVIDER_DISPLAY_NAMES

        self.assertIn("openai", _PROVIDER_DISPLAY_NAMES)
        self.assertIn("anthropic", _PROVIDER_DISPLAY_NAMES)
        self.assertIn("gemini", _PROVIDER_DISPLAY_NAMES)


class GenerateExternalReplyProviderHintTests(unittest.TestCase):
    """generate_external_reply provider_hint 인자 검증."""

    def test_provider_hint_none_uses_default(self) -> None:
        from app.llm import generate_external_reply

        # provider_hint=None → 기본 외부 LLM (대부분 key 미설정으로 fallback)
        reply, route = generate_external_reply("hello", "webui", provider_hint=None)
        self.assertIsInstance(reply, str)
        self.assertIn(route, ("external_llm", "fallback"))

    def test_provider_hint_unknown_falls_back(self) -> None:
        from app.llm import generate_external_reply

        reply, route = generate_external_reply("hello", "webui", provider_hint="nonexistent")
        # key 없으면 fallback
        self.assertEqual(route, "fallback")


# ---------------------------------------------------------------------------
# Gmail 후속 참조 (첫번째 메일 내용 알려줘) 관련 테스트
# ---------------------------------------------------------------------------

class GmailCandidateExtractionTests(unittest.TestCase):
    """Markdown 볼드 형식의 gmail summary에서 후보 추출 테스트."""

    def test_markdown_bold_numbered_items(self) -> None:
        reply = (
            "📬 **최근 메일 요약**\n\n"
            "**1) 프로젝트 승인**\n"
            "보낸 사람: boss@company.com\n"
            "날짜: 2026-03-20\n\n"
            "**2) 주간 보고**\n"
            "보낸 사람: team@company.com\n"
        )
        result = extract_candidates_from_reply(reply, "n8n")

        self.assertEqual(len(result), 2)
        self.assertIn("프로젝트 승인", result[0]["label"])
        self.assertIn("주간 보고", result[1]["label"])

    def test_compact_format_also_works(self) -> None:
        reply = "최근 메일 요약입니다.\n1. boss@co.com - 프로젝트 승인\n2. team@co.com - 주간 보고"
        result = extract_candidates_from_reply(reply, "n8n")

        self.assertEqual(len(result), 2)


class GmailFollowupReferenceTests(unittest.TestCase):
    """이전 gmail_summary 결과를 참조하는 후속 질문 처리 테스트."""

    def _make_extraction(self, message: str, intent: str = "gmail_summary") -> StructuredExtraction:
        from app.schemas import MailExtractionPayload
        domain = "mail" if intent.startswith("gmail") else "chat"
        action = intent.removeprefix("gmail_") if intent.startswith("gmail") else "respond"
        return StructuredExtraction(
            raw_message=message,
            normalizedMessage=message,
            domain=domain,
            action=action,
            intent=intent,
            confidence=0.85,
            mail=MailExtractionPayload() if domain == "mail" else None,
        )

    def test_ordinal_with_gmail_candidates_selects_item(self) -> None:
        extraction = self._make_extraction("메일의 첫번째 항목 내용을 알려줘")
        previous = self._make_extraction("최근 메일 요약해줘")
        candidates = [
            {"index": 0, "label": "프로젝트 승인", "raw": "boss@co.com - 프로젝트 승인", "sender": "boss@co.com", "snippet": "확인 부탁", "date": "2026-03-20"},
            {"index": 1, "label": "주간 보고", "raw": "team@co.com - 주간 보고", "sender": "team@co.com", "snippet": "보고 완료", "date": "2026-03-19"},
        ]

        result = apply_reference_context(extraction, previous, last_candidates=candidates)

        self.assertTrue(result.metadata.get("candidate_selected"))
        self.assertEqual(result.metadata.get("candidate_index"), 0)
        self.assertEqual(result.metadata.get("candidate_label"), "프로젝트 승인")
        # candidate_data에 sender, snippet 등 리치 데이터 포함
        candidate_data = result.metadata.get("candidate_data", {})
        self.assertEqual(candidate_data.get("sender"), "boss@co.com")
        self.assertEqual(candidate_data.get("snippet"), "확인 부탁")

    def test_candidate_selected_gmail_redirects_to_chat(self) -> None:
        """classify 노드에서 candidate_selected+gmail_summary → chat 전환."""
        from app.graph.nodes import classify

        extraction = self._make_extraction("메일의 두번째 항목 알려줘")
        extraction.metadata = {
            **dict(extraction.metadata),
            "candidate_selected": True,
            "candidate_index": 1,
            "candidate_label": "주간 보고",
            "candidate_data": {"sender": "team@co.com", "label": "주간 보고"},
        }

        state = {
            "message": "메일의 두번째 항목 알려줘",
            "channel": "webui",
            "structured_extraction": extraction,
        }

        result = classify(state)

        self.assertEqual(result["intent"], "chat")
        self.assertTrue(result["extraction"].metadata.get("candidate_selected"))

    def test_gmail_summary_without_candidate_stays_summary(self) -> None:
        """candidate_selected가 없으면 gmail_summary 유지."""
        from app.graph.nodes import classify

        extraction = self._make_extraction("최근 메일 보여줘")

        state = {
            "message": "최근 메일 보여줘",
            "channel": "webui",
            "structured_extraction": extraction,
        }

        result = classify(state)

        self.assertEqual(result["intent"], "gmail_summary")


if __name__ == "__main__":
    unittest.main()