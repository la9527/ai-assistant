# 자동화 Skill-First 아키텍처 설계안

## 목적

현재 자동화 도메인 전반은 `automation.py` 중심의 규칙 기반 intent 분류와 도메인별 parser 조합으로 운영되고 있다.
이 방식은 MVP 단계에서는 빠르지만, 도메인이 늘어날수록 아래 문제가 커진다.

- 자연스러운 사용자 표현이 특정 키워드 규칙과 충돌한다.
- calendar, mail, browser, macOS/PC 실행 자동화가 비슷한 문맥 표현을 공유하면서 intent 경계가 흔들린다.
- 기간 조회, 참조 표현, 후속 대화 문맥을 도메인마다 중복 구현하게 된다.
- `skills`, `LangGraph`, `MCP`, `structured extraction` 이 존재하지만, 운영 경로의 중심 추상화가 아직 아니다.

이 문서는 전체 자동화 도메인을 `skill-first + LLM structured extraction + executor abstraction` 구조로 재설계하는 공통 기준안을 정의한다.

핵심 목표는 아래와 같다.

- keyword 체크보다 자연어 중심으로 작업을 해석한다.
- `skills` 를 메타데이터가 아니라 실제 실행 단위로 승격한다.
- `LLM structured extraction` 을 도메인 공통 입력 해석 계층으로 사용한다.
- `MCP` 는 자연어 해석이 아니라 도구 실행 표준화 계층으로 사용한다.
- 현재 운영 중인 `n8n`, `browser-runner`, `macos-mcp-server`, 승인 티켓 구조를 깨지 않고 점진 전환한다.

---

## 적용 대상 도메인

이 설계는 아래 도메인에 공통 적용한다.

- Calendar 자동화
- Mail 자동화
- Browser 자동화
- macOS/PC 실행 자동화

도메인별 대표 작업은 아래와 같다.

| 도메인 | 작업 예시 |
|--------|-----------|
| calendar | 조회, 생성, 변경, 삭제 |
| mail | 검색, 목록, 상세, 답장, 이어쓰기, 초안, 발송 |
| browser | 검색, 읽기, 스크린샷, 추후 승인형 액션 |
| macOS/PC | Reminders, Finder, Notes, 볼륨, 다크모드, 추후 앱 제어 |

---

## 현재 구조의 한계

### 현재 처리 흐름

```text
사용자 메시지
  → classify_message_intent()
  → extract_structured_request()
      → rule-based baseline
      → 일부 intent 에 한해 structured extraction 보정
  → process_message()
  → executor 호출
  → 응답 포맷팅
```

### 구조적 문제

| 문제 | 설명 |
|------|------|
| intent 분류가 규칙 중심 | 전체 의미보다 특정 단어/표현에 민감하다 |
| extraction 적용 범위 불균형 | 일부 intent 만 LLM 보정이 켜져 있어 도메인별 일관성이 부족하다 |
| skill 추상화 미활용 | `BaseSkill` 인터페이스가 있어도 실제 주 경로는 `automation.py` 분기 중심이다 |
| executor 추상화 부족 | 도메인별 실행기가 공통 인터페이스 뒤에 숨지 않고 직접 라우팅된다 |
| 참조 해석 분산 | 기간 조회, 후보 선택, 후속 맥락 해석이 도메인별 예외 규칙으로 누적된다 |
| MCP 역할 불명확 | 설정 및 연결은 존재하지만, 어떤 도메인에서 어떻게 써야 하는지 기준이 약하다 |

---

## 왜 skill-first 로 가야 하는가

사용자는 도메인별로 아래처럼 자연어를 섞어 말한다.

### Calendar

- `이번 주 금요일 오후에 치과 일정 잡아줘`
- `방금 만든 일정 한 시간 뒤로 옮겨줘`
- `다음 주 초에 있는 회의들만 보여줘`

### Mail

- `이번 주에 온 결제 관련 메일 보여줘`
- `방금 본 메일에 정중하게 답장해줘`
- `지난주 금요일쯤 받은 메일 중 첫 번째를 자세히 보여줘`

### Browser

- `이 페이지 요약해줘`
- `구글에서 맥미니 MLX 성능 검색해줘`
- `이 사이트 화면 캡처해줘`

### macOS/PC 실행 자동화

- `볼륨 30으로 바꿔줘`
- `파인더로 Downloads 폴더 열어줘`
- `미리알림에 내일 오전 9시 은행 가기 추가해줘`

이 표현은 단순 keyword가 아니라 아래 조합을 필요로 한다.

- 작업 종류
- 시간 범위
- 참조 방식
- 위험도
- 실행 대상 도구

따라서 도메인별 자동화는 `intent keyword matching` 보다 `skill selection + structured extraction + validator + executor` 구조가 자연스럽다.

---

## 핵심 원칙

### 1. Skill은 실제 실행 단위다

각 자동화 능력은 독립된 skill 로 정의한다.

skill 은 최소 아래 책임을 가진다.

- 설명 가능한 메타데이터
- input schema
- extraction 힌트
- validation 규칙
- executor 연결 정보
- 승인 필요 여부

### 2. LLM은 skill 선택과 파라미터 추출에 사용한다

LLM이 해야 할 일:

- 어떤 skill 이 맞는지 선택
- 해당 skill 의 schema 에 맞는 파라미터 추출
- 기간 표현, 참조 표현, 후속 문맥을 구조화

LLM이 하지 않아야 할 일:

- 외부 서비스 credential 직접 처리
- 승인 우회
- 시스템 명령 즉시 실행

### 3. MCP는 실행 표준화 계층이다

MCP는 자연어 해석 수단이 아니라 도구 호출 인터페이스다.

적합한 역할:

- 외부 또는 분리된 도구를 표준 `tool` 인터페이스로 연결
- `browser`, `macOS`, 추후 `mail`, `calendar` executor 를 같은 방식으로 호출
- 로컬 시스템 도구를 프로세스 경계 뒤로 격리

부적합한 역할:

- intent 분류 대체
- 자연어 parsing 자체 대체

### 4. 읽기/쓰기/실행 위험도를 분리한다

| 계열 | 예시 | 승인 |
|------|------|------|
| read | calendar 조회, mail 상세, browser read/search | 기본 불필요 |
| write | 일정 생성/변경/삭제, 메일 발송/회신, Reminders 추가 | 필요 |
| system action | 파일 조작, 앱 실행, 브라우저 액션 자동화 | 기본 필요 |

---

## 목표 아키텍처

```text
사용자 메시지
  → Skill Catalog Loader
  → LLM Skill Selector
  → Structured Argument Extractor
  → Validator
  → Context Resolver
  → Approval Policy
  → Executor Router
      → n8n executor
      → api executor
      → mcp executor
      → local function executor
  → Response Formatter
```

### 처리 흐름 상세

```text
User message
  → 활성 skill 목록 구성
  → LLM이 skill_id + arguments JSON 반환
  → schema validation
  → missing field / clarification 판정
  → time/reference/context resolution
  → approval check
  → executor 호출
  → channel formatter
```

---

## 공통 SkillDescriptor 확장 방향

현재 `trigger_keywords` 중심 skill 정의를 아래 구조로 확장한다.

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
    executor_type: Literal["n8n", "api", "mcp", "local_function", "macos"]
    executor_ref: str
    approval_required: bool
    risk_level: Literal["low", "medium", "high"]
    enabled: bool = True
```

`trigger_keywords` 는 제거보다 축소가 맞다.

- 1차 빠른 필터 또는 fallback 용도로만 유지
- 최종 선택은 LLM skill selector 가 담당

---

## 도메인별 설계 적용

## 1. Calendar

### 목표 skill

- `calendar.search`
- `calendar.create`
- `calendar.update`
- `calendar.delete`

### Calendar에서 LLM이 잘해야 하는 것

- `이번 주`, `다음 주 초`, `내일 오전`, `금요일쯤` 같은 기간 표현 해석
- `방금 만든 일정`, `그 회의`, `오후 일정` 같은 참조 표현 해석

### 권장 schema 예시

- `timeRange`
- `title`
- `searchTitle`
- `startAt`
- `endAt`
- `timezone`

### 실행 계층

- 1차: `n8n calendar executor`
- 2차: private `calendar MCP executor` 가능

---

## 2. Mail

메일 도메인 상세 설계는 [docs/mail-skill-first-architecture.md](mail-skill-first-architecture.md)를 참조한다.

### 목표 skill

- `mail.search`
- `mail.list`
- `mail.read`
- `mail.thread_read`
- `mail.compose`
- `mail.send`
- `mail.reply`
- `mail.thread_reply`

### 실행 계층

- 1차: `n8n mail executor`
- 2차: private `mail MCP executor`

---

## 3. Browser

### 목표 skill

- `browser.search`
- `browser.read`
- `browser.screenshot`
- 추후: `browser.action` 계열

### Browser에서 LLM이 잘해야 하는 것

- 사용자의 목표를 검색인지 읽기인지 캡처인지 구분
- URL이 없을 때 검색과 읽기 중 적절한 경로 선택
- 후속 문맥에서 `이 페이지`, `방금 연 사이트` 같은 참조 해석

### 권장 구조

- read/search/screenshot 은 low-risk read skill
- click/type/submit 계열은 high-risk action skill 로 별도 분리

### 실행 계층

- 현재: `browser-runner API executor`
- 확장: `browser MCP executor`

Browser는 MCP와 궁합이 좋지만, 읽기 계열과 action 계열을 분리해야 한다.

---

## 4. macOS/PC 실행 자동화

### 목표 skill

- `system.reminder_create`
- `system.note_create`
- `system.volume_get`
- `system.volume_set`
- `system.darkmode_toggle`
- `system.finder_open`
- 추후: `system.app_open`, `system.file_move`, `system.shortcut_run`

### 왜 이 도메인이 MCP와 특히 잘 맞는가

- 로컬 시스템 제어는 프로세스 경계 분리가 중요하다.
- 호스트 권한, 파일 접근, AppleScript 실행을 API 프로세스 내부에 두는 것보다 MCP 서버 격리가 낫다.
- 현재 `macos-mcp-server` 방향은 장기 구조에 잘 맞는다.

### 권장 구조

- low-risk 조회: 즉시 실행 가능
- 상태 변경 또는 시스템 액션: 승인 필요
- 파일/앱/브라우저 조작은 task log 와 approval payload 를 반드시 남긴다.

---

## 공통 Structured Extraction 설계

### 목표

모든 도메인에서 같은 envelope 를 사용한다.

```json
{
  "skillId": "calendar.create",
  "confidence": 0.92,
  "needsClarification": false,
  "approvalRequired": true,
  "missingFields": [],
  "arguments": {}
}
```

### 공통 해석 대상

- 기간 표현
- 참조 표현
- 위험도 힌트
- 사용자 선호

### 공통 Resolver 계층

Resolver 는 domain 공통과 domain 전용으로 나눈다.

- 공통 resolver
  - `time_range_normalizer`
  - `ordinal_reference_resolver`
  - `session_context_resolver`
- 도메인 전용 resolver
  - `mail_target_resolver`
  - `calendar_target_resolver`
  - `browser_target_resolver`
  - `system_target_resolver`

---

## MCP 적용 기준

### 바로 MCP가 적합한 도메인

- macOS/PC 실행 자동화
- 일부 browser action 자동화
- 추후 파일 시스템 제어

### 당장은 executor abstraction 뒤에 두는 것이 나은 도메인

- mail
- calendar

이유:

- 이미 `n8n + OAuth + 승인 + 감사` 구조가 안정적으로 존재한다.
- 먼저 LLM skill selection 과 schema extraction 을 정리하는 편이 구조적 이득이 크다.

### 결론

MCP는 전체 구조에서 중요하지만, 1차 목표는 `도메인 해석을 skill-first 로 바꾸는 것` 이다.

---

## 단계별 전환 계획

### Phase 1. 공통 문서와 schema 정리

- 전체 자동화 도메인 공통 `skill-first` 기준 확정
- domain 별 skill catalog 정리
- 공통 structured extraction envelope 통일

### Phase 2. LLM Skill Selector 도입

- `classify_message_intent()` 를 fallback 으로 축소
- active skill catalog 기반 selector prompt 추가
- domain 공통 `skillId + arguments` JSON 반환 구조 도입

### Phase 3. Domain Skill 구현체 작성

- calendar skill 구현체
- mail skill 구현체
- browser skill 구현체
- system skill 구현체

### Phase 4. Resolver / Validator 분리

- time range
- reference resolution
- approval validation
- executor-specific validation

### Phase 5. Executor Router 추상화

- `N8NExecutor`
- `APIExecutor`
- `MCPExecutor`
- `LocalFunctionExecutor`

### Phase 6. 선택적 MCP 심화 전환

- browser action MCP
- macOS/PC MCP
- 추후 private mail/calendar MCP

---

## 구현 우선순위 제안

### 우선순위 1

- 공통 skill selector 설계
- 공통 extraction envelope 구현
- mail, calendar 부터 전환

### 우선순위 2

- browser read/search/screenshot 전환
- system 조회/변경 skill 전환

### 우선순위 3

- executor router 공통화
- approval payload 공통화

### 우선순위 4

- browser action / macOS action 의 MCP 중심 정리

---

## 최종 결론

이 방향은 mail 에만 해당되지 않는다.

- calendar 도 keyword 기반 분류보다 `skill + 기간 해석 + context resolution` 이 맞다.
- browser 도 `읽기`, `검색`, `캡처`, `액션` 을 skill 로 분리해야 자연스럽다.
- macOS/PC 실행 자동화도 단일 parser 가 아니라 `system skill` 집합으로 가야 한다.

따라서 권장 방향은 아래 한 줄로 요약된다.

```text
전체 자동화 도메인을 skill-first + LLM structured extraction 으로 전환하고,
실행 계층은 n8n/api/mcp executor 로 분리해 점진적으로 표준화한다.
```
