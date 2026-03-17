import unittest

from app.automation import _calendar_payload_to_request
from app.automation import apply_reference_context
from app.automation import extract_user_memory_candidates
from app.llm import _build_local_reply_messages
from app.automation import _mail_payload_to_compose_request
from app.automation import _mail_payload_to_reply_request
from app.automation import _merge_mail_payload
from app.automation import _normalize_gmail_reply_body
from app.automation import parse_calendar_request
from app.automation import parse_gmail_compose_request
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


if __name__ == "__main__":
    unittest.main()