# 메일 Skill-First 아키텍처 설계안

## 목적

현재 메일 도메인은 `automation.py` 안에서 규칙 기반 의도 분류, 파라미터 추출, 실행 라우팅, 응답 포맷팅이 강하게 결합되어 있다.
이 구조는 빠르게 기능을 붙이기에는 유리하지만, 아래 문제가 반복된다.

- 사용자의 자연스러운 표현이 특정 키워드 규칙과 충돌한다.
- 메일 조회, 상세, 답장, 스레드 이어쓰기, 초안, 발송이 비슷한 표현을 공유해 의도 경계가 흔들린다.
- 기간 표현, 참조 표현, 후속 대화 문맥을 rule만으로 처리하려고 하면서 예외 규칙이 증가한다.
- `skills` 와 `MCP` 가 존재하지만 실제 메일 처리의 1급 추상화로 작동하지 않는다.

이 문서는 메일 기능을 `skill-first` 구조로 전환하는 설계안을 정의한다.

핵심 목표는 아래와 같다.

- 특정 문구 체크보다 자연어 중심으로 메일 작업을 해석한다.
- `skills` 를 메타데이터가 아니라 실제 실행 단위로 승격한다.
- `LLM structured extraction` 을 메일 도메인의 기본 입력 해석 계층으로 사용한다.
- `MCP` 는 자연어 해석이 아니라 도구 실행 표준화 계층으로 사용한다.
- 현재 동작 중인 `n8n + Gmail OAuth + 승인 티켓` 흐름을 깨지 않고 점진적으로 전환한다.

---

## 현재 구조 진단

### 현재 메일 처리 흐름

```text
사용자 메시지
  → classify_message_intent()
  → extract_structured_request()
      → rule-based baseline
      → 일부 intent 에 한해 LLM structured extraction 보정
  → process_message()
      → gmail_summary | gmail_detail | gmail_send | gmail_reply | gmail_thread_reply
  → n8n Gmail workflow 호출
  → 응답 포맷팅
```

### 현재 구조의 문제

| 문제 | 설명 |
|------|------|
| 의도 선택이 규칙 중심 | 사용자의 자연어 전체 의미보다 특정 단어와 라벨 표현에 민감하다 |
| extraction 적용 범위 제한 | structured extraction이 일부 intent 중심이라 mail 전반의 일관성이 부족하다 |
| skill 추상화 미활용 | `SkillDescriptor`, `BaseSkill` 이 정의돼 있으나 메일 처리의 중심이 아니다 |
| 실행기 추상화 부족 | 메일 실행은 사실상 `automation.py → n8n webhook` 직결 구조다 |
| MCP 역할 불명확 | 설정과 개념은 있으나 메일 도메인에서 왜/어떻게 쓸지 명확하지 않다 |

### 왜 특정 단어 기반 방식이 부자연스러운가

사용자는 아래처럼 다양한 표현을 섞어 쓴다.

- `이번 주에 온 결제 관련 메일 보여줘`
- `방금 본 메일에 정중하게 답장해줘`
- `아까 그 사람이 보낸 메일 내용 확인해서 이어서 회신해줘`
- `지난주 금요일쯤 받은 메일 중 첫 번째를 자세히 보여줘`

이 표현은 단일 키워드가 아니라 다음 요소가 함께 필요하다.

- 작업 종류: 조회, 상세, 답장, 이어쓰기, 초안, 발송
- 시간 범위: 오늘, 이번 주, 지난주 후반, 최근, 3일 내
- 참조 방식: 첫 번째, 방금 본, 그 메일, 같은 스레드
- 실행 위험도: 읽기인지, 실제 발송인지

따라서 메일은 keyword 분류보다 `skill selection + structured extraction + validator` 구조가 훨씬 자연스럽다.

---

## 목표 원칙

### 1. 메일은 skill 단위로 나눈다

메일 도메인을 하나의 거대한 parser 로 유지하지 않고, 명확한 작업 단위로 분리한다.

초기 권장 skill 목록:

- `mail.search`
- `mail.list`
- `mail.read`
- `mail.thread_read`
- `mail.compose`
- `mail.send`
- `mail.reply`
- `mail.thread_reply`

현재 intent 와의 매핑은 아래처럼 점진적으로 맞춘다.

| 현재 intent | 목표 skill |
|-------------|------------|
| `gmail_summary` | `mail.search` 또는 `mail.list` |
| `gmail_list` | `mail.list` |
| `gmail_detail` | `mail.read` |
| `gmail_thread` | `mail.thread_read` |
| `gmail_draft` | `mail.compose` |
| `gmail_send` | `mail.send` |
| `gmail_reply` | `mail.reply` |
| `gmail_thread_reply` | `mail.thread_reply` |

### 2. LLM은 skill 선택과 파라미터 추출에 사용한다

LLM이 해야 할 일:

- 사용자의 발화에서 가장 적절한 skill 선택
- 해당 skill input schema 에 맞는 구조화 파라미터 추출
- 기간 표현, 참조 표현, 후속 문맥을 반영한 JSON 생성

LLM이 하지 않아야 할 일:

- OAuth 토큰 직접 처리
- Gmail API 직접 호출
- 승인 정책 우회
- 감사 로그 없이 위험 작업 수행

### 3. MCP는 실행 표준화에 사용한다

MCP는 자연어 해석 도구가 아니라 외부 도구 실행 인터페이스다.

메일 도메인에서 MCP가 적합한 역할:

- Gmail 관련 도구를 표준 `tool` 인터페이스로 노출
- 내부 executor 와 외부 도구 서버를 동일한 인터페이스로 호출
- 이후 `n8n` 대체 또는 래핑 지점으로 사용

메일 도메인에서 MCP가 적합하지 않은 역할:

- 자연어 분류 자체 대체
- 사용자 계정 권한을 모델 근처에 직접 노출

### 4. 읽기와 쓰기를 명확히 분리한다

- 읽기 계열: low risk, 승인 없음
- 쓰기 계열: high risk, 승인 필수

| 계열 | skill | 승인 |
|------|-------|------|
| read | `mail.search`, `mail.list`, `mail.read`, `mail.thread_read` | 불필요 |
| write | `mail.compose`, `mail.send`, `mail.reply`, `mail.thread_reply` | 필요 |

---

## 목표 아키텍처

```text
사용자 메시지
  → Mail Skill Selector
      → LLM 기반 skill 선택
      → LLM 기반 structured extraction
  → Skill Validator
  → Context Resolver
      → session state
      → previous candidates
      → memory / references
  → Approval Policy
  → Executor Router
      → n8n executor
      → MCP executor
      → local executor
  → Response Formatter
```

### 처리 흐름 상세

```text
User message
  → skill catalog 생성
  → LLM이 skill_id + payload JSON 반환
  → schema validation
  → missing field / clarification 판정
  → reference resolution
  → approval check
  → executor 호출
  → channel formatter
```

---

## Skill 카탈로그 설계

### SkillDescriptor 확장 방향

현재 `SkillDescriptor` 는 `trigger_keywords` 중심이다.
메일 도메인에서는 아래 정보가 더 중요하다.

```python
class SkillDescriptor(BaseModel):
    skill_id: str
    name: str
    domain: str
    action: str
    description: str
    intent_examples: list[str]
    disambiguation_hints: list[str]
    input_schema: dict
    output_schema: dict | None = None
    executor_type: Literal["n8n", "mcp", "local_function", "api"]
    executor_ref: str
    approval_required: bool
    risk_level: Literal["low", "medium", "high"]
    enabled: bool = True
```

### mail skill 예시

#### `mail.search`

- 역할: 조건 기반 메일 탐색
- 예시 발화:
  - `이번 주 받은 메일 보여줘`
  - `최근 결제 관련 메일 찾아줘`
  - `지난 3일 동안 온 Gmail 목록 보여줘`

입력 schema 예시:

```json
{
  "timeRange": {
    "type": "object",
    "properties": {
      "kind": { "type": "string" },
      "startAt": { "type": ["string", "null"] },
      "endAt": { "type": ["string", "null"] },
      "raw": { "type": "string" }
    }
  },
  "sender": { "type": ["string", "null"] },
  "subjectContains": { "type": ["string", "null"] },
  "keywords": { "type": "array", "items": { "type": "string" } },
  "limit": { "type": ["integer", "null"] },
  "unreadOnly": { "type": ["boolean", "null"] }
}
```

#### `mail.read`

- 역할: 특정 메일 상세 조회
- 예시 발화:
  - `첫 번째 메일 자세히 보여줘`
  - `아까 본 메일 본문 보여줘`
  - `message id xxx 메일 읽어줘`

#### `mail.reply`

- 역할: 특정 메일에 회신
- 예시 발화:
  - `그 메일에 정중하게 답장해줘`
  - `방금 본 메일에 확인했다고 답장해줘`
  - `제목 주간 보고 메일에 답장해줘`

입력 schema 예시:

```json
{
  "targetReference": {
    "type": "object",
    "properties": {
      "referenceType": { "type": "string" },
      "messageId": { "type": ["string", "null"] },
      "threadId": { "type": ["string", "null"] },
      "ordinal": { "type": ["integer", "null"] },
      "searchQuery": { "type": ["string", "null"] },
      "fromSession": { "type": ["boolean", "null"] }
    }
  },
  "body": { "type": "string" },
  "tone": { "type": ["string", "null"] },
  "cc": { "type": "array", "items": { "type": "string" } },
  "bcc": { "type": "array", "items": { "type": "string" } }
}
```

---

## LLM Skill Selector 설계

### 기존 방식

- keyword 기반 `intent` 추정
- 일부 intent 에만 structured extraction 보정

### 목표 방식

LLM에게 아래를 동시에 요청한다.

1. 이 발화에 맞는 `skill_id`
2. 해당 skill schema에 맞는 `arguments`
3. 부족한 정보가 있으면 `needsClarification`
4. 위험 작업이면 `approvalRequired`

### 출력 envelope 예시

```json
{
  "skillId": "mail.reply",
  "confidence": 0.91,
  "needsClarification": false,
  "approvalRequired": true,
  "missingFields": [],
  "arguments": {
    "targetReference": {
      "referenceType": "subject_search",
      "searchQuery": "subject:\"주간 보고\" newer_than:30d"
    },
    "body": "확인했습니다. 진행 부탁드립니다.",
    "tone": "polite",
    "cc": [],
    "bcc": []
  }
}
```

### prompt 입력 구성

LLM에 제공할 입력:

- 활성화된 mail skill 목록
- 각 skill description
- 각 skill input schema 요약
- 최근 세션 컨텍스트
- 이전 후보 목록
- baseline parser 결과

중요한 점은 baseline을 `정답` 이 아니라 `hint` 로 내려야 한다는 것이다.

---

## 기간 조회 설계

질문에서 언급한 `기간 조회`는 규칙보다 LLM + 정규화 레이어가 적합하다.

### 목표

아래 표현을 자연스럽게 처리한다.

- `오늘`
- `어제`
- `최근`
- `최근 3일`
- `이번 주`
- `지난주`
- `이번 달 초`
- `지난 금요일쯤`

### 권장 방식

1. LLM은 먼저 `raw time intent` 를 구조화한다.
2. 서버는 timezone 기반으로 이를 절대 시간 범위로 확정한다.

예시:

```json
{
  "timeRange": {
    "kind": "relative_week",
    "raw": "이번 주",
    "startAt": null,
    "endAt": null
  }
}
```

서버 정규화 후:

```json
{
  "timeRange": {
    "kind": "relative_week",
    "raw": "이번 주",
    "startAt": "2026-03-16T00:00:00+09:00",
    "endAt": "2026-03-22T23:59:59+09:00"
  }
}
```

이 방식의 장점:

- 자연어 해석은 LLM이 맡는다.
- 최종 시간 결정은 서버가 맡는다.
- timezone, locale, 운영 규칙을 backend가 통제할 수 있다.

---

## Reference Resolver 설계

메일은 단일 요청보다 후속 대화가 중요하다.

예시:

- `첫 번째 메일 자세히 보여줘`
- `그 메일에 답장해줘`
- `같은 스레드 계속 이어줘`

### Resolver 입력

- 현재 skill arguments
- 세션의 `last_candidates`
- 최근 assistant 응답의 items/context
- 마지막 성공한 mail action

### Resolver 역할

- ordinal reference 해결
- `그 메일`, `아까 본 메일`, `같은 스레드` 같은 지시어 해석
- 검색 query fallback 생성

### 중요한 설계 포인트

LLM이 reference를 추출하더라도, 실제 해석은 세션 상태가 해야 한다.
즉:

- LLM: `ordinal=1`, `referenceType=session_candidate`
- backend resolver: 실제 `messageId/threadId` 매핑

---

## Executor 계층 설계

### 원칙

자연어 계층과 실행 계층을 분리한다.

```text
skill selection/extraction ≠ executor
```

### 1차 권장안

당장은 현재 안정적으로 동작하는 `n8n` 기반 executor를 유지한다.

- `mail.search` → `n8n_gmail_summary_webhook`
- `mail.read` → `n8n_gmail_detail_webhook`
- `mail.reply` → `n8n_gmail_reply_webhook`
- `mail.send` → `n8n_gmail_send_webhook`

### 2차 확장안

이후 `MCP mail executor` 를 도입해 아래 형태로 전환 가능하게 만든다.

```text
ExecutorRouter
  → N8NExecutor
  → MCPExecutor
  → LocalFunctionExecutor
```

### MCP가 메일에 어울리는 지점

적합한 형태:

- 내부 Gmail 도구를 private MCP server 로 제공
- Assistant backend는 그 MCP tool 을 신뢰 경계 안에서 호출
- 외부 커뮤니티 MCP를 직접 메일 계정에 붙이지 않고, 내부 통제형 MCP를 사용

권장 mail MCP tools 예시:

- `mail.search`
- `mail.read_message`
- `mail.read_thread`
- `mail.create_draft`
- `mail.send_message`
- `mail.reply_message`

---

## Approval 및 보안 설계

메일 쓰기 작업은 현재와 같이 backend가 승인 정책을 유지해야 한다.

### 승인 적용 대상

- `mail.compose`
- `mail.send`
- `mail.reply`
- `mail.thread_reply`

### 승인 시점

- skill selection/extraction 후
- resolver/validator 완료 후
- executor 호출 직전

즉, 승인 대상은 자연어 원문이 아니라 `검증된 skill arguments` 여야 한다.

이렇게 해야 사용자가 실제로 승인하는 대상이 명확해진다.

---

## 단계별 전환 계획

### Phase 1. 문서 및 스키마 정비

- mail skill catalog 정의
- 공통 mail skill input schema 도입
- 기간 조회용 `timeRange` 구조 도입
- 기존 `gmail_*` intent 와 신규 `mail.*` skill 매핑 정의

### Phase 2. LLM Skill Selector 도입

- `classify_message_intent()` 를 mail 도메인에서는 fallback 으로 축소
- `mail skill selector` 전용 prompt 추가
- 기존 baseline parser 결과를 hint 로 전달
- `skillId + arguments` JSON 반환 구조 구현

### Phase 3. Mail Skill 구현체 작성

- `MailSearchSkill`
- `MailReadSkill`
- `MailReplySkill`
- `MailSendSkill`
- `MailThreadReplySkill`

각 skill은 `BaseSkill` 을 구현한다.

### Phase 4. Resolver / Validator 분리

- session candidate resolver
- time range normalizer
- mail target resolver
- mail approval validator

### Phase 5. Executor 추상화

- 기존 n8n 호출을 `N8NMailExecutor` 로 캡슐화
- LangGraph / FastAPI 에서 직접 webhook path 를 알지 않도록 분리

### Phase 6. 선택적 MCP 도입

- internal MCP mail server 초안 구현
- `MCPMailExecutor` 추가
- skill executor_type 기준으로 `n8n ↔ mcp` 교체 가능화

---

## 구현 우선순위 제안

### 우선순위 1

- mail skill catalog 설계 확정
- LLM skill selector 초안 구현
- `mail.reply`, `mail.thread_reply`, `mail.read` 먼저 전환

이유:

- 현재 가장 문맥 의존이 크고, rule 기반 충돌이 자주 나는 영역이다.

### 우선순위 2

- 기간 조회 강화를 위한 `mail.search`, `mail.list` 전환
- `timeRange` 정규화 계층 도입

### 우선순위 3

- `mail.compose`, `mail.send` 전환
- approval payload UX 개선

### 우선순위 4

- internal MCP mail executor 검토 및 PoC

---

## 권장 결론

### 무엇을 바꿔야 하는가

- 메일 도메인 분류의 주도권을 keyword rule 에서 LLM skill selection 으로 이동한다.
- `skills` 를 실제 실행 단위로 승격한다.
- structured extraction 을 mail 전반의 기본 계층으로 확장한다.
- 현재의 `n8n` 실행은 유지하되 executor abstraction 뒤로 숨긴다.
- MCP는 메일 자연어 해석 수단이 아니라 향후 executor 표준화 계층으로 도입한다.

### 무엇을 당장 바꾸지 않는가

- Gmail 계정 연결 방식을 곧바로 외부 MCP 서버로 교체하지 않는다.
- 승인 정책과 session state 관리를 모델 쪽으로 넘기지 않는다.
- rule parser 를 즉시 삭제하지 않는다. fallback 과 validation hint 로 유지한다.

### 최종 판단

질문에서 제안한 방향은 맞다.

- 특정 단어 기반 매칭은 메일 도메인에 장기적으로 부적합하다.
- `skills + LLM structured extraction` 이 더 자연스럽다.
- `MCP` 도 유용하지만, 실행 표준화 계층으로 써야 한다.
- 메일 계정 연결은 backend 통제형 구조가 우선이다.

따라서 권장안은 다음 한 줄로 정리된다.

```text
메일 도메인은 skill-first + LLM structured extraction 으로 전환하고,
실행 계층은 n8n executor 를 유지한 채 추후 MCP executor 로 확장한다.
```
