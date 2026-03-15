import unittest

from app.automation import _calendar_payload_to_request
from app.automation import _mail_payload_to_compose_request
from app.automation import _mail_payload_to_reply_request
from app.automation import _merge_mail_payload
from app.automation import _normalize_gmail_reply_body
from app.automation import parse_calendar_request
from app.automation import parse_gmail_compose_request
from app.automation import parse_gmail_reply_request
from app.schemas import CalendarExtractionPayload
from app.schemas import MailExtractionPayload


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


if __name__ == "__main__":
    unittest.main()