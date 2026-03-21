"""mail 도메인 스킬 메타데이터."""

from app.skills.base import SkillDescriptor

GMAIL_SUMMARY_SKILL = SkillDescriptor(
    skill_id="gmail_summary",
    name="메일 요약",
    description="받은편지함의 최근 메일을 요약한다.",
    domain="mail",
    action="summary",
    trigger_keywords=["메일", "이메일", "gmail", "email", "편지함", "수신", "요약", "최근", "받은편지함", "inbox"],
    intent_examples=["최근 메일 보여줘", "이번 주 받은편지함 요약해줘"],
    disambiguation_hints=["목록/요약 중심 조회", "상세 본문 조회가 아니면 summary 우선"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_SUMMARY_WEBHOOK_PATH",
    approval_required=False,
    risk_level="low",
)

GMAIL_LIST_SKILL = SkillDescriptor(
    skill_id="gmail_list",
    name="메일 목록 조회",
    description="조건에 맞는 메일 목록을 조회한다.",
    domain="mail",
    action="list",
    trigger_keywords=["메일", "이메일", "gmail", "목록", "리스트", "더보기", "여러 건"],
    intent_examples=["결제 관련 메일 목록 보여줘", "최근 메일 10건만 보여줘"],
    disambiguation_hints=["여러 건 나열 요청", "상세 본문 요청이 없으면 list"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_SUMMARY_WEBHOOK_PATH",
    approval_required=False,
    risk_level="low",
)

GMAIL_DETAIL_SKILL = SkillDescriptor(
    skill_id="gmail_detail",
    name="메일 상세 조회",
    description="선택한 메일의 상세 정보와 본문을 조회한다.",
    domain="mail",
    action="detail",
    trigger_keywords=["메일", "이메일", "gmail", "상세", "자세히", "본문", "원문", "내용"],
    intent_examples=["첫 번째 메일 자세히 보여줘", "방금 본 메일 본문 읽어줘"],
    disambiguation_hints=["단일 메일 본문 조회", "번호/메시지 ID 지정 시 detail"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_DETAIL_WEBHOOK_PATH",
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
    intent_examples=["보고 메일 초안 작성해줘", "test@example.com로 초안 만들어줘"],
    disambiguation_hints=["실제 발송 전 초안 저장", "승인 필요"],
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
    intent_examples=["메시지 보내줘", "test@example.com로 메일 발송해줘"],
    disambiguation_hints=["실제 발송", "승인 필요"],
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
    intent_examples=["그 메일에 답장해줘", "방금 본 메일에 확인했다고 회신해줘"],
    disambiguation_hints=["기존 메일 대상 회신", "승인 필요"],
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
    intent_examples=["같은 스레드로 이어서 답장해줘", "메일에 이어서 회신해줘"],
    disambiguation_hints=["같은 thread 유지", "승인 필요"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_REPLY_WEBHOOK_PATH",
    approval_required=True,
    risk_level="high",
)

SKILLS = [
    GMAIL_SUMMARY_SKILL,
    GMAIL_LIST_SKILL,
    GMAIL_DETAIL_SKILL,
    GMAIL_DRAFT_SKILL,
    GMAIL_SEND_SKILL,
    GMAIL_REPLY_SKILL,
    GMAIL_THREAD_REPLY_SKILL,
]
