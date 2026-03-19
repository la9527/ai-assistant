"""mail 도메인 스킬 메타데이터."""

from app.skills.base import SkillDescriptor

GMAIL_SUMMARY_SKILL = SkillDescriptor(
    skill_id="gmail_summary",
    name="메일 요약",
    description="받은편지함의 최근 메일을 요약한다.",
    domain="mail",
    action="summary",
    trigger_keywords=["메일", "이메일", "gmail", "email", "편지함", "수신", "요약", "최근", "받은편지함", "inbox"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_SUMMARY_WEBHOOK_PATH",
    approval_required=False,
    risk_level="low",
)

GMAIL_DRAFT_SKILL = SkillDescriptor(
    skill_id="gmail_draft",
    name="메일 초안 작성",
    description="Gmail에 초안(draft)을 생성한다. 수신자, 제목, 본문이 필요하다.",
    domain="mail",
    action="draft",
    trigger_keywords=["메일", "이메일", "gmail", "email", "초안", "draft"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_DRAFT_WEBHOOK_PATH",
    approval_required=True,
    risk_level="medium",
)

GMAIL_SEND_SKILL = SkillDescriptor(
    skill_id="gmail_send",
    name="메일 발송",
    description="Gmail로 메일을 직접 발송한다. 수신자, 제목, 본문이 필요하다.",
    domain="mail",
    action="send",
    trigger_keywords=["메일", "이메일", "gmail", "email", "발송", "send"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_SEND_WEBHOOK_PATH",
    approval_required=True,
    risk_level="high",
)

GMAIL_REPLY_SKILL = SkillDescriptor(
    skill_id="gmail_reply",
    name="메일 회신",
    description="수신된 메일에 답장을 보낸다. 스레드 또는 메시지 ID가 필요하다.",
    domain="mail",
    action="reply",
    trigger_keywords=["메일", "이메일", "gmail", "email", "답장", "회신", "reply"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_REPLY_WEBHOOK_PATH",
    approval_required=True,
    risk_level="high",
)

GMAIL_THREAD_REPLY_SKILL = SkillDescriptor(
    skill_id="gmail_thread_reply",
    name="메일 스레드 이어쓰기",
    description="기존 메일 스레드에 이어서 답장한다.",
    domain="mail",
    action="thread_reply",
    trigger_keywords=["메일", "이메일", "gmail", "email", "이어", "이어서", "계속", "thread", "스레드"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_REPLY_WEBHOOK_PATH",
    approval_required=True,
    risk_level="high",
)

SKILLS = [
    GMAIL_SUMMARY_SKILL,
    GMAIL_DRAFT_SKILL,
    GMAIL_SEND_SKILL,
    GMAIL_REPLY_SKILL,
    GMAIL_THREAD_REPLY_SKILL,
]
