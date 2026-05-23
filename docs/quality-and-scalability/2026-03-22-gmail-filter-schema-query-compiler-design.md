# Gmail Filter Schema 및 Query Compiler 설계 초안 (2026-03-22)

## 문서 목적

- 기존 검토 문서의 `바로 추진 가능한 작업` 1, 2, 3을 실제 설계 초안 수준으로 구체화한다.
- 현재 `MailExtractionPayload` 와 `assistant-gmail-summary` workflow 제약을 기준으로 단계적 전환 방안을 제시한다.
- 향후 Gmail bulk action 과 calendar mutation safety 정책까지 확장 가능한 공통 모델을 정리한다.

## 범위

이번 문서는 아래 항목에 집중한다.

1. 실행 경로 통합 — 데드코드 정리 및 skill 단일 경로 확정
2. Gmail filter schema 초안 정의
3. `_build_gmail_search_query` 리팩터링 초안
4. `assistant-gmail-summary` workflow 의 mailbox 제약 점검 및 개선안
5. 보강 사항 — 동의어 통합, filters/searchQuery 우선순위, LLM prompt 영향, 렌더링 영향, 테스트 선행 추가

## 현재 상태 요약

### 현재 `MailExtractionPayload`

현재 payload 는 아래와 같은 혼합형 구조다.

- 조회용 필드: `searchQuery`, `limit`, `cursor`, `groupByDate`, `detailLevel`, `selectedIndexes`
- 작성/회신용 필드: `recipients`, `cc`, `bcc`, `subject`, `body`, `threadReference`, `messageReference`

이 구조의 문제는 아래와 같다.

- read 와 write/action 의미가 한 타입에 섞여 있다.
- query 의미가 구조가 아니라 문자열로만 남는다.
- preview, approval, snapshot execution 개념을 넣기 어렵다.

### 현재 `assistant-gmail-summary` workflow 제약

현재 workflow 는 아래 특징이 있다.

- Gmail `message.getAll` 에 `labelIds=[INBOX]` 고정
- `q=searchQuery` 전달
- `cursor` 를 입력으로 받지 않음
- `nextCursor` 는 계산해서 반환하지만 실제 Gmail pagination token 은 아님

즉 현재 `cursor` 는 UI 힌트 수준이고, executor 관점의 실제 pagination 이 아니다.

## 0. 실행 경로 통합 — 데드코드 정리 및 skill 단일 경로 확정

### 배경

코드 검증 결과, `graph/nodes.py` 에 `execute_gmail_summary`, `execute_gmail_detail`, `execute_gmail_compose`, `execute_gmail_reply`, `execute_calendar_summary`, `execute_calendar_write` 함수가 존재하지만, `graph/workflow.py` 의 실제 그래프 빌드에는 등록되지 않는 데드코드임을 확인했다.

`build_assistant_graph()` 에 등록된 실행 노드는 아래 4개뿐이다.

- `execute_skill` — skill registry 기반 통합 실행
- `execute_web_search`
- `execute_mcp_tool`
- `execute_chat`

Gmail, Calendar 모든 intent 는 `_route_after_validate` → `get_skill_runtime(intent)` → `"execute_skill"` 또는 `"check_approval_skill"` → `"execute_skill"` 을 통해 skill runtime 으로 실행된다.

### 현재 상태 정리

| 코드 | 현재 상태 | 작업 |
|------|---------|------|
| `graph/nodes.py`: `execute_gmail_summary` | 데드코드 | 제거 |
| `graph/nodes.py`: `execute_gmail_detail` | 데드코드 | 제거 |
| `graph/nodes.py`: `execute_gmail_compose` | 데드코드 | 제거 |
| `graph/nodes.py`: `execute_gmail_reply` | 데드코드 | 제거 |
| `graph/nodes.py`: `execute_calendar_summary` | 데드코드 | 제거 |
| `graph/nodes.py`: `execute_calendar_write` | 데드코드 | 제거 |
| `graph/nodes.py`: `_build_mail_result_context` | 데드코드 (동일 함수가 automation.py 에 존재) | 제거 |
| `graph/nodes.py`: `_build_calendar_n8n_failure_reply` | 데드코드 전용 helper | 제거 |
| `graph/workflow.py` docstring | 옛 개별 노드 라우팅 설명 | 현행 구조로 갱신 |
| `skills/mail/implementation.py` | **활성 실행 경로** | 유지 |
| `automation.py`: `_build_mail_result_context` | **활성** | 유지 |
| `automation.py`: `_merge_mail_request_context` | **활성** | 유지 |

### 제거 작업 방식

1. `graph/nodes.py` 에서 위 데드코드 함수들을 삭제한다.
2. 관련 import 가 없으므로 다른 모듈에 영향 없다.
3. `graph/workflow.py` 상단 docstring 을 현재 실제 그래프 구조로 업데이트한다.

### 제거 후 기대 효과

- Gmail/Calendar 실행 로직이 skill 한 곳에서만 유지보수된다.
- 향후 `filters`, `mailboxScope`, `cursor`, `safety` 도입 시 변경 지점이 단일 경로로 제한된다.
- `_build_mail_result_context` 중복이 사라져 result context 확장이 일관적이다.
- 코드 읽기 시 혼동이 줄어든다.

### 우선순위

이 작업은 기능 영향 없이 즉시 진행 가능하다. filter schema 도입이나 query compiler 리팩터링보다 먼저 수행하는 것이 좋다.

## 1. Gmail Filter Schema 초안 정의

## 설계 원칙

1. canonical model 은 문자열 query 가 아니라 구조화된 filter 여야 한다.
2. query string 은 Gmail API 호출 직전의 파생 값이어야 한다.
3. action 계열은 filter 외에 selection, preview, snapshot 개념을 가져야 한다.
4. 하위 호환을 위해 기존 `MailExtractionPayload` 는 단계적으로 확장한다.

## 권장 전환 방식

### 단기 권장안

- `MailExtractionPayload` 에 새 필드를 추가해 호환성 유지
- 내부적으로는 새 `filters` 와 `selection` 필드를 우선 사용
- 기존 `searchQuery` 는 compiler 결과를 담는 하위 호환 필드로 유지

### 중기 권장안

- `MailReadPayload`, `MailActionPayload`, `MailTargetSnapshot` 를 별도 타입으로 분리
- `StructuredExtraction.mail` 이 union 성격을 갖게 하거나 envelope 구조로 재편

## 단기 초안 스키마

```python
class MailQueryDateRange(BaseModel):
    relative_days: int | None = Field(default=None, alias="relativeDays")
    relative_weeks: int | None = Field(default=None, alias="relativeWeeks")
    start_at: str | None = Field(default=None, alias="startAt")
    end_at: str | None = Field(default=None, alias="endAt")


class MailQueryFilters(BaseModel):
    mailbox_scope: str | None = Field(default=None, alias="mailboxScope")
    categories: list[str] = Field(default_factory=list)
    labels_include: list[str] = Field(default_factory=list, alias="labelsInclude")
    labels_exclude: list[str] = Field(default_factory=list, alias="labelsExclude")
    sender: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body_keywords: list[str] = Field(default_factory=list, alias="bodyKeywords")
    free_keywords: list[str] = Field(default_factory=list, alias="freeKeywords")
    unread_only: bool | None = Field(default=None, alias="unreadOnly")
    read_only: bool | None = Field(default=None, alias="readOnly")
    has_attachment: bool | None = Field(default=None, alias="hasAttachment")
    important_only: bool | None = Field(default=None, alias="importantOnly")
    starred_only: bool | None = Field(default=None, alias="starredOnly")
    date_range: MailQueryDateRange | None = Field(default=None, alias="dateRange")


class MailSelectionSpec(BaseModel):
    selection_mode: str | None = Field(default=None, alias="selectionMode")
    selected_indexes: list[int] = Field(default_factory=list, alias="selectedIndexes")
    selected_message_ids: list[str] = Field(default_factory=list, alias="selectedMessageIds")
    selected_thread_ids: list[str] = Field(default_factory=list, alias="selectedThreadIds")


class MailExecutionSafety(BaseModel):
    preview_required: bool | None = Field(default=None, alias="previewRequired")
    snapshot_id: str | None = Field(default=None, alias="snapshotId")
    max_items: int | None = Field(default=None, alias="maxItems")
```

기존 `MailExtractionPayload` 에는 아래와 같이 단계적으로 필드를 추가하는 방식이 현실적이다.

```python
class MailExtractionPayload(BaseModel):
    ...
    filters: MailQueryFilters | None = None
    selection: MailSelectionSpec | None = None
    safety: MailExecutionSafety | None = None
```

## 의미 규칙

### `mailboxScope`

권장 값:

- `default`
- `inbox`
- `all_mail`
- `sent`
- `drafts`
- `trash`
- `spam`

설명:

- `default` 는 기존 동작을 유지하기 위한 호환 모드
- `all_mail` 은 Gmail node 에 `labelIds` 를 강제하지 않는 모드

### `categories`

권장 canonical 값:

- `promotions`
- `social`
- `updates`
- `forums`

### `selectionMode`

권장 값:

- `auto_single`
- `single`
- `multi`
- `all`
- `snapshot`

설명:

- read-only list/detail 에서는 `single`, `multi` 정도면 충분
- destructive action 에서는 `all` 또는 `snapshot` 이 중요

## 스키마 확장 시 기대 효과

1. query string 역해석이 줄어든다.
2. preview/action safety 모델을 추가하기 쉬워진다.
3. calendar mutation 에도 같은 target/snapshot 정책을 복제할 수 있다.

## 2. `_build_gmail_search_query` 리팩터링 초안

## 현재 문제

현재 함수는 아래 역할을 한 번에 수행한다.

- 자연어 정규화
- 날짜 표현 해석
- 상태 표현 해석
- 필드 세그먼트 추출
- keyword 보조 추론
- Gmail query string 생성

이렇게 되면 함수가 커지고, 자연어 해석 계층과 query compiler 계층이 분리되지 않는다.

## 권장 리팩터링 목표

`_build_gmail_search_query(message)` 를 최종 public-like helper 로 유지하더라도, 내부는 3단계로 나누는 것이 좋다.

### 단계 1. 자연어 -> filter draft

역할:

- 자연어 메시지에서 구조화된 `MailQueryFilters` draft 생성
- 이 계층은 rule-based 또는 향후 LLM planner 결과를 받아도 된다.

권장 함수 예시:

```python
def _extract_mail_query_filters(message: str) -> MailQueryFilters:
    ...
```

이 함수가 맡을 것:

- 날짜 범위
- mailbox scope
- category
- sender, recipient, subject
- body keyword
- unread, attachment, important, starred

### 단계 2. filter normalization

역할:

- 동의어를 canonical 값으로 정규화
- 충돌 필드 정리
- default mailbox 정책 적용

권장 함수 예시:

```python
def _normalize_mail_query_filters(filters: MailQueryFilters) -> MailQueryFilters:
    ...
```

예시 정책:

- `광고`, `홍보`, `뉴스레터`, `프로모션 메일` -> `categories=["promotions"]`
- `받은편지함`, `인박스` -> `mailboxScope="inbox"`
- `메일 전체`, `전체 메일함` -> `mailboxScope="all_mail"`

### 단계 3. filter -> Gmail query compiler

역할:

- 정규화된 canonical filters 를 Gmail native query string 으로 변환

권장 함수 예시:

```python
def _compile_gmail_query(filters: MailQueryFilters) -> str | None:
    ...
```

이 함수는 deterministic 해야 한다.

### 단계 4. 하위 호환 wrapper

```python
def _build_gmail_search_query(message: str) -> str | None:
    filters = _extract_mail_query_filters(message)
    normalized = _normalize_mail_query_filters(filters)
    return _compile_gmail_query(normalized)
```

## 추천 세부 분해

아래 수준까지 쪼개두면 테스트가 쉬워진다.

- `_extract_mail_time_filters`
- `_extract_mail_state_filters`
- `_extract_mail_mailbox_filters`
- `_extract_mail_category_filters`
- `_extract_mail_field_filters`
- `_normalize_mailbox_scope`
- `_normalize_mail_categories`
- `_compile_mailbox_scope`
- `_compile_date_range`
- `_compile_field_queries`

## 리팩터링 시 유지해야 할 호환성

1. 기존 `searchQuery` 결과 문자열은 당분간 최대한 동일하게 유지
2. 현재 테스트 케이스는 깨지지 않게 점진 적용
3. 기존 `gmail_summary`, `gmail_list`, `gmail_detail`, `gmail_reply` 호출부는 즉시 전면 수정하지 않음

## 리팩터링 시 추가해야 할 테스트

### 리팩터링 전에 먼저 추가해야 할 케이스

현재 `GmailSearchQueryTests` 는 6개 케이스뿐이다. 리팩터링 전에 아래를 먼저 추가해야 동의어 정규화가 기존 결과를 깨지 않는지 검증할 수 있다.

권장 추가 케이스:

- `프로모션 메일 보여줘` → `category:promotions`
- `보낸편지함 메일 보여줘` → `in:sent`
- `광고 메일 보여줘` → (향후 synonym 확장 기준선)
- `어제 메일 보여줘` → `after:YYYY/MM/DD before:YYYY/MM/DD`
- `지난 2주 메일` → `after:YYYY/MM/DD`
- `읽지 않은 중요 메일` → `is:unread is:important`
- `별표 메일` → `is:starred`

### 리팩터링 후 추가할 케이스

1. synonym normalization 테스트
- `광고 메일` -> `promotions`
- `전체 메일함` -> `all_mail`

2. compiler 테스트
- canonical filter 입력 -> 기대 Gmail query 출력

3. backwards compatibility 테스트
- 기존 자연어 입력 -> 기존과 동일한 주요 query part 포함

## 3. `assistant-gmail-summary` workflow mailbox 제약 점검

> **참고**: `assistant-gmail-detail` workflow 도 동일하게 `labelIds=[INBOX]` 가 고정돼 있다. `mailboxScope` 정책 도입 시 summary 와 detail 모두 동시 변경해야 한다.

## 현재 제약

현재 workflow 는 Gmail fetch node 에서 아래 조건을 강제한다.

- `labelIds=[INBOX]`
- `q=searchQuery`

이 설계는 아래 문제를 만든다.

### 문제 1. `all_mail` 조회가 불가능하다.

- 사용자가 `전체 메일함`, `최근 30일 프로모션 메일`, `보낸 메일 포함 전체` 를 의도해도 실제 executor 는 INBOX 로 제한된다.

### 문제 2. query 와 labelIds 가 충돌할 수 있다.

예시:

- query: `in:sent after:2026/02/20`
- labelIds: `INBOX`

이 경우 실제 의도는 보낸편지함인데 workflow 는 INBOX 만 보게 된다.

### 문제 3. category 기반 정리 작업의 기반이 약하다.

- `category:promotions` 는 Gmail query 수준에서는 유효해도, INBOX 고정 때문에 기대 결과가 줄어들 수 있다.

### 문제 4. 현재 `cursor` 가 실제 pagination 이 아니다.

- workflow 는 Gmail API page token 을 사용하지 않는다.
- `nextCursor` 는 마지막 item 의 internalDate 를 돌려주지만, executor 가 이 값을 읽어 다음 query 를 보정하지 않는다.

## 권장 mailbox 정책

### 정책 A. mailboxScope 기반 labelIds 결정

권장 변환:

- `default` -> 기존 하위 호환 정책 적용
- `inbox` -> `labelIds=[INBOX]`
- `all_mail` -> `labelIds` 미설정
- `sent` -> `labelIds=[SENT]` 또는 query `in:sent` 중 하나로 통일
- `drafts` -> `labelIds=[DRAFT]` 또는 query `in:drafts`

권장 사항:

- 가능하면 `labelIds` 와 `in:*` query 를 중복해서 쓰지 않고 한쪽으로 통일하는 편이 낫다.
- 읽기 전용 summary/list 는 `mailboxScope` 를 executor layer 에서 명시적으로 처리하는 편이 query 충돌을 줄인다.

### 정책 B. 기본값 재정의

현재 `default=INBOX` 는 하위 호환에는 유리하지만 확장성에는 제약이 있다.

권장 절충안:

- `default` 는 현재처럼 inbox 중심 유지
- 다만 filters 또는 canonical model 에 `all_mail` 이 명시되면 `labelIds` 를 제거
- `categories` 가 설정된 경우도 inbox 고정이 정말 맞는지 재검토

### 정책 C. `categories` 와 mailboxScope 조합 규칙

권장 규칙:

- `mailboxScope=inbox` + `categories=[promotions]` 는 허용하되 결과가 비어도 이상하지 않음
- `mailboxScope=all_mail` + `categories=[promotions]` 는 bulk maintenance 의 기본 조회 모드

## cursor 개선 초안

### 현재 상태

- `nextCursor` 는 internalDate 기반 UI cursor 에 가깝다.

### 권장 방향

단기:

- `cursor` 를 실제 executor 입력으로 받더라도, `before:` 또는 internalDate 기반 추가 필터로 query 를 좁히는 임시 모델 도입 검토

중기:

- n8n Gmail node 가 지원하는 pagination 토큰을 활용할 수 있는지 확인
- 지원이 부족하면 Gmail REST API 직접 호출 경로를 별도 executor 로 두는 것이 현실적일 수 있다.

## 바로 적용 가능한 workflow 변경 초안

### 입력 payload 예시

```json
{
  "searchQuery": "category:promotions after:2026/02/20",
  "limit": 20,
  "groupByDate": true,
  "mailboxScope": "all_mail"
}
```

### n8n normalize 정책

- `mailboxScope=inbox` -> labelIds=`[INBOX]`
- `mailboxScope=all_mail` -> labelIds unset
- `mailboxScope=sent` -> labelIds=`[SENT]` 또는 query rewrite

## 권장 구현 순서

0. **데드코드 제거** — `graph/nodes.py` 의 미사용 execute 함수 삭제 및 `graph/workflow.py` docstring 갱신
1. **리팩터링 전 테스트 추가** — 기존 동작의 기준선 확보
2. 스키마에 `filters` 와 `mailboxScope` 추가
3. `_build_gmail_search_query` 내부를 extract/normalize/compile 로 분해
4. summary 및 detail workflow 에 `mailboxScope` 처리 추가
5. category + all_mail 조합 테스트 추가
6. `format_gmail_summary` 의 mailbox direction-aware 렌더링 검토
7. 이후 destructive action preview workflow 설계 시작

## Calendar 공통 정책과의 연결

이번 설계는 Gmail 전용처럼 보이지만, 실제로는 아래 공통 정책으로 캘린더에도 연결된다.

- 자연어 -> canonical target/filter
- canonical target -> executor query
- ambiguous target 은 preview-first
- approval 후 snapshot target 실행

즉 Gmail filter schema 는 `mail` 도메인의 canonical model 이고, 캘린더에서는 같은 위치에 `calendar target model` 이 들어가면 된다.

## 보강 사항: 동의어 통합 테이블

설계 초안의 2단계는 category synonym 만 강조했지만, 실제 코드에는 mailbox, state, action 동의어도 하드코딩돼 있다. 통합 synonym table 을 단일 소스로 관리해야 한다.

### Category Synonym Table

| 입력 | canonical |
|------|----------|
| `프로모션`, `promotions`, `광고`, `홍보`, `뉴스레터`, `이벤트`, `마케팅 메일` | `promotions` |
| `소셜`, `social` | `social` |
| `업데이트`, `updates` | `updates` |
| `포럼`, `forums` | `forums` |

### Mailbox Synonym Table

| 입력 | canonical |
|------|----------|
| `받은편지함`, `인박스`, `수신 메일`, `inbox` | `inbox` |
| `보낸편지함`, `보낸 메일`, `sent mail` | `sent` |
| `초안`, `draft`, `drafts` | `drafts` |
| `휴지통`, `trash` | `trash` |
| `스팸`, `spam` | `spam` |
| `전체 메일함`, `전체 메일`, `메일 전체`, `all mail` | `all_mail` |

### State Synonym Table

| 입력 | canonical field | Gmail query |
|------|----------------|------------|
| `읽지 않`, `안 읽`, `unread` | `unreadOnly=true` | `is:unread` |
| `읽은`, `read` | `readOnly=true` | `is:read` |
| `첨부`, `attachment` | `hasAttachment=true` | `has:attachment` |
| `중요`, `important` | `importantOnly=true` | `is:important` |
| `별표`, `starred` | `starredOnly=true` | `is:starred` |

### Action Synonym Table (향후 destructive action 용)

| 입력 | canonical action |
|------|----------------|
| `지워`, `삭제`, `정리`, `휴지통` | `trash` |
| `보관` | `archive` |
| `읽음 처리` | `mark_read` |
| `안 읽음 처리` | `mark_unread` |

이 테이블을 `_normalize_mail_query_filters` 에서 단일 dict 로 관리한다.

## 보강 사항: `filters` vs `searchQuery` 우선순위 정책

기존 `searchQuery` 와 신규 `filters` 가 공존하는 구간에서의 우선순위 규칙을 아래와 같이 확정한다.

### 규칙

1. `filters` 가 비어 있지 않으면 → `filters → compile` 결과를 `searchQuery` 로 사용한다.
2. `filters` 가 없고 `searchQuery` 만 있으면 → 기존 호환 경로를 사용한다.
3. `filters` 와 `searchQuery` 가 둘 다 있으면 → `filters → compile` 결과가 우선이고, `searchQuery` 는 무시한다.
4. LLM structured extraction 은 `filters` 를 채우는 방향으로 유도하되, 당분간 `searchQuery` 직접 수정도 허용한다.

### skill 적용 위치

```python
# GmailSummarySkill.execute 개념 수준
def execute(self, params, context):
    extraction = params
    if extraction.mail and extraction.mail.filters:
        # filters → compile → searchQuery
        query = _compile_gmail_query(
            _normalize_mail_query_filters(extraction.mail.filters)
        )
    elif extraction.mail and extraction.mail.search_query:
        # 기존 호환 경로
        query = extraction.mail.search_query
    else:
        query = None
    extra["searchQuery"] = query or ""
```

## 보강 사항: `MailExtractionPayload` 확장 시 LLM prompt 영향

`structured_extraction_targets` 에 `gmail_reply`, `gmail_thread_reply` 가 포함되어 있으므로, LLM structured extraction prompt 가 `MailExtractionPayload` 필드 이름을 참조한다.

`filters`, `selection`, `safety` 필드를 추가하면:

1. LLM prompt 의 JSON schema 예시를 갱신해야 한다.
2. LLM 이 `filters` 를 채울 수 있도록 prompt 에 가이드를 추가해야 한다.
3. 단기적으로는 기존 필드(`searchQuery`, `subject`, `sender`, `body` 등)를 유지하고, `filters` 는 선택적 수준으로 두는 것이 안전하다.
4. 중기적으로는 `gmail_summary`, `gmail_list` 를 `structured_extraction_targets` 에 추가하고 LLM 이 filters 를 직접 생성하게 하는 방향도 검토한다.

## 보강 사항: `mailboxScope` 도입 시 렌더링 영향

`mailboxScope=all_mail` 또는 `sent` 가 도입되면 보낸 메일도 결과에 포함될 수 있다.

현재 `format_gmail_summary` 는 `sender - subject` 구조로만 렌더링한다. 하지만:

- 보낸 메일에서는 sender 가 나 자신이므로 recipient 이 더 중요하다.
- `in:sent` 또는 `SENT` label 이 포함된 결과에서는 `→ recipient - subject` 식으로 렌더링하는 것이 자연스럽다.

권장 방식:

- n8n 응답에 `labelIds` 또는 `mailDirection` hint 를 포함시키는 방안
- 또는 sender 가 내 계정과 일치하면 `→ {to}` 로 표시하는 formatter 측 로직

이 부분은 `mailboxScope` 적용 후에 formatter 를 함께 수정해야 한다.

## 보강 사항: `_extract_labeled_segment` 의 stop labels 관리

현재 `_build_gmail_search_query` 는 `GMAIL_SEARCH_STOP_LABELS` 상수에 의존해서 `_extract_labeled_segment` 의 추출 범위를 제한한다. 이 상수의 내용에 따라 `제목 A 내용 B` 같은 복합 쿼리의 정확도가 달라진다.

리팩터링 시 권장 방식:

- `_extract_mail_field_filters` 내부에서 stop labels 를 함수 파라미터 또는 모듈 수준 상수로 명시적으로 관리한다.
- 신규 필드 라벨이 추가될 때 stop labels 에도 자동으로 반영되는 구조가 이상적이다.

## Step 5. 동의어 정규화 및 category + all_mail 조합 테스트

### 배경

Step 3 에서 3단계 파이프라인(extract → normalize → compile)을 구현했지만, `_normalize_mail_query_filters` 는 pass-through 상태다. 동의어 확장과 조합 테스트를 추가해야 파이프라인이 실질적으로 동작한다.

### 5-1. 동의어 정규화 구현

`_normalize_mail_query_filters` 에 아래 동의어 테이블을 적용한다.

#### Category Synonym Table

| 입력 패턴 | canonical 값 |
|-----------|-------------|
| `광고`, `홍보`, `뉴스레터`, `마케팅`, `이벤트`, `프로모션`, `promotions` | `promotions` |
| `소셜`, `social` | `social` |
| `업데이트`, `updates` | `updates` |
| `포럼`, `forums` | `forums` |

#### Mailbox Synonym Table

| 입력 패턴 | canonical 값 |
|-----------|-------------|
| `전체 메일함`, `전체 메일`, `메일 전체`, `all_mail`, `all mail` | `all_mail` |
| `받은편지함`, `인박스`, `수신 메일`, `inbox` | `inbox` |
| `보낸편지함`, `보낸 메일`, `sent`, `sent mail` | `sent` |
| `초안`, `drafts`, `draft` | `drafts` |
| `휴지통`, `trash` | `trash` |
| `스팸`, `spam` | `spam` |

#### 구현 방식

1. `_extract_mail_query_filters` 에서 신규 동의어 키워드를 감지하도록 확장한다.
   - 카테고리: `광고`, `홍보`, `뉴스레터`, `마케팅` 추가 → raw 값 `promotions` 으로 매핑
   - 메일함: `전체 메일함`, `전체 메일`, `메일 전체` → `all_mail` 매핑, `인박스` → `inbox` 매핑
   - `휴지통`, `스팸` → `trash`, `spam` 매핑

2. `_normalize_mail_query_filters` 는 canonical 값 보정 safety net 으로 구현한다.
   - categories 필드의 원소를 canonical 테이블로 정규화
   - mailbox_scope 를 canonical 테이블로 정규화
   - 향후 LLM 이 raw 한국어 값을 채울 경우의 보정 계층

```python
_CATEGORY_SYNONYMS: dict[str, str] = {
    "광고": "promotions", "홍보": "promotions", "뉴스레터": "promotions",
    "마케팅": "promotions", "이벤트": "promotions",
    "프로모션": "promotions", "promotions": "promotions",
    "소셜": "social", "social": "social",
    "업데이트": "updates", "updates": "updates",
    "포럼": "forums", "forums": "forums",
}

_MAILBOX_SYNONYMS: dict[str, str] = {
    "전체 메일함": "all_mail", "전체 메일": "all_mail", "메일 전체": "all_mail",
    "all_mail": "all_mail", "all mail": "all_mail",
    "받은편지함": "inbox", "인박스": "inbox", "수신 메일": "inbox", "inbox": "inbox",
    "보낸편지함": "sent", "보낸 메일": "sent", "sent": "sent", "sent mail": "sent",
    "초안": "drafts", "drafts": "drafts", "draft": "drafts",
    "휴지통": "trash", "trash": "trash",
    "스팸": "spam", "spam": "spam",
}
```

### 5-2. 테스트 추가 계획

#### A. 동의어 정규화 end-to-end 테스트

| 입력 | 기대 query 포함 |
|------|---------------|
| `광고 메일 보여줘` | `category:promotions` |
| `홍보 메일 보여줘` | `category:promotions` |
| `뉴스레터 메일 보여줘` | `category:promotions` |
| `전체 메일함 메일 보여줘` | `_extract` 에서 mailboxScope=all_mail, query 에는 in:* 없음 |
| `인박스 메일 보여줘` | `in:inbox` |
| `휴지통 메일 보여줘` | `in:trash` |
| `스팸 메일 보여줘` | `in:spam` |

#### B. category + all_mail 조합 테스트

| 입력 | mailboxScope | categories | 기대 query |
|------|-------------|------------|-----------|
| `전체 메일함에서 프로모션 메일` | `all_mail` | `[promotions]` | `category:promotions` (in:* 없음) |
| `전체 메일함에서 광고 메일` | `all_mail` | `[promotions]` | `category:promotions` (in:* 없음) |
| `전체 메일함에서 소셜 메일` | `all_mail` | `[social]` | `category:social` (in:* 없음) |

#### C. compiler 단위 테스트

`_compile_gmail_query` 에 구조화된 `MailQueryFilters` 를 직접 넣는 테스트로, 자연어 파싱과 분리하여 compiler 의 deterministic 동작을 검증한다.

| filters 입력 | 기대 query |
|-------------|-----------|
| `categories=["promotions"]` | `category:promotions` |
| `mailbox_scope="sent", date_range.relative_days=7` | `newer_than:7d in:sent` |
| `unread_only=True, important_only=True` | `is:unread is:important` |
| `sender="test@example.com"` | `from:test@example.com` |

### 5-3. 기대 효과

- 동의어 확장으로 `광고 메일 삭제해줘` 같은 자연어 표현의 정확도가 올라간다.
- `all_mail` + category 조합으로 INBOX 제약 없이 전체 메일함에서 카테고리별 조회가 가능해진다.
- normalize 계층이 실질적으로 동작하여 향후 LLM extraction 결과도 안전하게 정규화된다.

## Step 6. format_gmail_summary 메일함 방향 인식 렌더링

### 배경

`mailboxScope=sent` 또는 `all_mail` 도입 후 보낸 메일이 결과에 포함될 수 있다. 현재 `_format_single_mail_item` 은 항상 `보낸 사람: {sender}` 로 렌더링하므로, 보낸 메일에서는 sender 가 본인이 되어 정보 가치가 낮다.

### 6-1. n8n workflow 변경

`assistant-gmail-summary.json` 의 Code node 에서 각 item 에 `toRecipients` 필드를 추가한다.

```javascript
const toRecipients = readHeader(headers, 'To') || '';
return {
  ...existingFields,
  toRecipients,
};
```

또한 응답 JSON 최상위에 `mailboxScope` 를 echo 한다.

```javascript
return [{
  json: {
    ...existingResponse,
    mailboxScope: payload.mailboxScope ?? 'default',
  },
}];
```

### 6-2. formatter 변경

`_format_single_mail_item` 에 `mailbox_scope` 파라미터를 추가하거나, `raw_body` 에서 `mailboxScope` 를 읽어 방향을 판단한다.

#### 렌더링 규칙

| 조건 | 표시 방식 |
|------|---------|
| `mailboxScope` 가 `sent` | `받는 사람: {toRecipients}` |
| `mailboxScope` 가 `drafts` | `받는 사람: {toRecipients}` |
| 그 외 (inbox, all_mail, default) | `보낸 사람: {sender}` (기존 동작 유지) |

`_format_gmail_items_markdown` 이 `mailbox_scope` 를 결정하여 `_format_single_mail_item` 에 전달한다.

```python
def _format_single_mail_item(item: dict, position: int, *, grouped: bool, sent_mode: bool = False) -> list[str]:
    ...
    if sent_mode:
        to_recipients = _clean_mail_text(item.get("toRecipients"), "수신자 미상")
        lines = [f"**{idx}) {subject}{status}**", f"받는 사람: {to_recipients}"]
    else:
        lines = [f"**{idx}) {subject}{status}**", f"보낸 사람: {sender}"]
    ...
```

compact 포맷(`_format_gmail_items_compact`)도 동일 로직 적용:

```python
for item in items:
    if sent_mode:
        contact = item.get("toRecipients", "수신자 미상")
    else:
        contact = item.get("sender", "발신자 미상")
    lines.append(f"{idx}. {contact} - {subject}")
```

### 6-3. GmailSummarySkill candidates 변경

`GmailSummarySkill.execute()` 에서 candidates 에 `toRecipients` 도 포함한다.

```python
"toRecipients": item.get("toRecipients") or item.get("to_recipients") or "",
```

### 6-4. 테스트 계획

단위 테스트 대상:

- `_format_single_mail_item` 에 `sent_mode=True` 전달 시 `받는 사람:` 표시 확인
- `_format_gmail_items_markdown` 에 `mailboxScope=sent` 포함된 raw_body 전달 시 전체 렌더링 확인
- `_format_gmail_items_compact` 동일

### 6-5. 기대 효과

- 보낸 메일함 조회 시 실질적으로 유용한 정보(수신자)가 표시된다.
- `전체 메일함` 조회 시에는 현재와 동일하게 발신자를 표시하되, 향후 per-item 방향 감지로 확장 가능하다.

## Step 7. 파괴적 메일 액션 preview-first 설계

### 7-1. 개요

현재 Gmail 도메인에는 조회(summary/list/detail)와 작성(draft/send/reply) 경로만 있다. 삭제, 보관, 읽음 처리 같은 파괴적 bulk action 은 별도 intent, skill, workflow 가 필요하다.

### 7-2. 신규 intent

| intent | 설명 | approval | risk_level |
|--------|------|----------|------------|
| `gmail_trash` | 메일을 휴지통으로 이동 | 필수 | high |
| `gmail_archive` | 메일을 보관 처리 | 필수 | medium |
| `gmail_mark_read` | 메일을 읽음 처리 | 선택적 | low |

### 7-3. 키워드 분류

```python
GMAIL_TRASH_KEYWORDS = ("삭제", "지워", "지우", "정리", "휴지통", "trash", "delete")
GMAIL_ARCHIVE_KEYWORDS = ("보관", "archive")
GMAIL_MARK_READ_KEYWORDS = ("읽음 처리", "읽음처리", "mark read")
```

`classify_message_intent` 분기 시 Gmail keyword + trash/archive/mark 키워드 조합으로 분류한다. trash 키워드는 calendar_delete 와 겹칠 수 있으므로, `has_gmail_keyword and not has_calendar_context` 조건을 우선 검사한다.

### 7-4. preview-first 실행 흐름

```
사용자 입력: "최근 30일 프로모션 메일 삭제해줘"
    │
    ├─ classify → gmail_trash
    ├─ extract_filters → {categories: [promotions], date_range: {relative_days: 30}}
    ├─ compile_query → "newer_than:30d category:promotions"
    │
    ├─ [Phase 1: Preview]
    │   ├─ n8n preview webhook → 대상 메일 수 + 샘플 5건
    │   ├─ preview 응답 생성:
    │   │   "프로모션 메일 42건을 찾았습니다."
    │   │   "최근 5건: ..."
    │   │   "승인하면 이 42건을 휴지통으로 이동합니다."
    │   └─ approval ticket 생성 (preview_snapshot 포함)
    │
    ├─ [Phase 2: Approval]
    │   ├─ 사용자 승인 (기존 approval flow 활용)
    │   └─ ticket payload 에 snapshot_id 포함
    │
    └─ [Phase 3: Execution]
        ├─ snapshot 기반 message_ids 로 실행
        ├─ n8n bulk action webhook → Gmail batchModify/trash
        └─ 결과 응답: "42건을 휴지통으로 이동했습니다."
```

### 7-5. 스킬 설계

#### Descriptor

```python
GMAIL_TRASH_SKILL = SkillDescriptor(
    skill_id="gmail_trash",
    name="메일 삭제",
    description="조건에 맞는 메일을 휴지통으로 이동한다.",
    domain="mail",
    action="trash",
    trigger_keywords=["메일", "이메일", "gmail", "삭제", "지워", "정리", "휴지통"],
    intent_examples=["프로모션 메일 삭제해줘", "최근 30일 광고 메일 정리해줘"],
    executor_type="n8n",
    executor_ref="N8N_GMAIL_BULK_ACTION_WEBHOOK_PATH",
    approval_required=True,
    risk_level="high",
)
```

#### Skill Implementation (Phase 1: Preview)

```python
class GmailTrashSkill(_BaseMailSkill):
    descriptor_model = GMAIL_TRASH_SKILL

    async def execute(self, params, context):
        extraction = params
        # 1. filters 에서 query 컴파일
        filters = extraction.mail.filters if extraction.mail else None
        if not filters:
            return {"reply": "삭제 대상을 특정할 수 없습니다. 검색 조건을 지정해주세요."}

        query = _compile_gmail_query(_normalize_mail_query_filters(filters))

        # 2. preview 검색 (summary webhook 동일, limit=30)
        preview_result = run_n8n_automation_raw(...)

        # 3. preview 응답 생성
        count = preview_result.get("count", 0)
        sample_items = preview_result.get("items", [])[:5]
        reply = f"조건에 맞는 메일 {count}건을 찾았습니다.\n"
        reply += "승인하면 이 메일들을 휴지통으로 이동합니다."

        # 4. approval ticket 에 snapshot (message_ids) 포함
        return {
            "reply": reply,
            "route": "n8n",
            "approval_context": {
                "action": "trash",
                "message_ids": [item["messageId"] for item in preview_result.get("items", [])],
                "count": count,
                "query": query,
            },
        }
```

### 7-6. n8n 신규 workflow

이번 단계에서는 n8n workflow JSON 은 설계만 한다. 실제 구현은 Gmail bulk action API 테스트 이후 진행한다.

#### `assistant-gmail-bulk-action` workflow 구조

```
Webhook (POST)
  → Validate action type (trash/archive/mark_read)
  → Gmail batchModify 또는 messages.trash 반복 호출
  → 결과 집계
  → Respond to Webhook
```

#### 입력 payload

```json
{
  "action": "trash",
  "messageIds": ["msg1", "msg2", ...],
  "snapshotId": "snap-xxx"
}
```

#### 출력 payload

```json
{
  "action": "trash",
  "processed": 42,
  "failed": 0,
  "reply": "42건의 메일을 휴지통으로 이동했습니다."
}
```

### 7-7. approval payload 확장

기존 approval ticket 의 `pending_action` 에 아래 필드를 추가한다.

- `preview_message_ids`: preview 시점에 확인된 대상 목록
- `preview_count`: 대상 건수
- `preview_query`: 사용된 검색 쿼리 (감사 로그용)

승인 후 실행 시 `preview_message_ids` 기반으로 n8n bulk action webhook 을 호출한다. 재검색하지 않으므로 preview 와 실행 대상이 일치한다.

### 7-8. 이번 단계 구현 범위

| 항목 | 이번 단계 | 향후 |
|------|---------|------|
| intent 분류 키워드 | ✅ 완료 | - |
| SkillDescriptor 등록 | ✅ 완료 | - |
| Skill 클래스 (preview-first) | ✅ 완료 (스캐폴딩) | n8n workflow 연결 후 완성 |
| registry 오탐 방지 (risk_level high/medium → 2+ keyword) | ✅ 완료 | - |
| n8n bulk action workflow | 설계만 | Gmail API 테스트 후 구현 |
| snapshot 저장 (Redis/DB) | 설계만 | approval ticket payload 임시 사용 |
| rollback/undo | 미착수 | 별도 설계 필요 |

### 7-9. 캘린더 공통 정책 연결

이 preview-first 흐름은 `calendar_delete` 에도 동일하게 적용할 수 있다. 현재 calendar_delete 는 승인은 있지만 preview 가 없어 `getAll limit=1` 결과를 바로 삭제한다. 향후:

- calendar_delete 에도 `preview → approval → snapshot execution` 적용
- `preview_event_id`, `preview_title`, `preview_time` 을 approval payload 에 포함

## 최종 제안

이번 단계의 최적 전략은 아래와 같다.

0. ~~**데드코드 제거를 먼저 수행한다.**~~ (완료)
1. ~~`MailExtractionPayload` 확장 방식으로 먼저 진입한다.~~ (완료)
2. ~~`_build_gmail_search_query` 는 wrapper 로 남기고 내부를 compiler 구조로 재편한다.~~ (완료)
3. ~~`assistant-gmail-summary` 및 `assistant-gmail-detail` workflow 의 `INBOX` 고정은 `mailboxScope` 정책으로 완화한다.~~ (완료)
4. ~~이 단계가 끝난 뒤 preview/snapshot 기반 action workflow 로 넘어간다.~~ (아래 단계로 진행)
5. ~~동의어 정규화 및 category + all_mail 조합 테스트 추가~~ (완료)
6. ~~format_gmail_summary 의 메일함 방향 인식 렌더링~~ (완료)
7. ~~파괴적 메일 액션 preview-first 스캐폴딩 (intent 키워드 + skill descriptor + skill 스캐폴딩)~~ (완료)

이 순서면 현재 동작을 크게 깨지 않으면서도, `최근 30일 광고 메일 삭제` 같은 향후 요구를 수용할 수 있는 구조로 자연스럽게 이동할 수 있다.