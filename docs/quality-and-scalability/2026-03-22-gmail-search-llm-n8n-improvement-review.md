# Gmail 검색, LLM, n8n 연계 개선 검토 (2026-03-22)

## 문서 목적

- 현재 Gmail 조회 경로에서 `_build_gmail_search_query` 가 맡는 역할을 구조적으로 정리한다.
- 로컬 LLM이 실제로 개입하는 범위와 개입하지 않는 범위를 구분한다.
- FastAPI 구조화 추출 결과가 n8n Gmail workflow 호출로 이어지는 실제 경로를 정리한다.
- 향후 `최근 30일 광고 메일만 삭제` 같은 복합 작업을 지원하려면 무엇을 바꿔야 하는지 검토한다.

## 이번 검토의 핵심 결론

- 현재 Gmail 요약 및 목록 조회는 LLM 중심 구조가 아니라 규칙 기반 query builder 중심 구조다.
- 로컬 LLM structured extraction 은 현재 `gmail_reply`, `gmail_thread_reply`, `calendar_delete` 같은 일부 intent 에만 적용된다.
- Gmail 읽기 경로는 `자연어 -> 규칙 기반 searchQuery 생성 -> n8n Gmail 조회 -> formatter 렌더링` 흐름이 핵심이다.
- Gmail 회신 경로는 `자연어 -> baseline 추출 -> 선택적으로 LLM 보정 -> n8n 검색 -> 대상 재선정 -> 회신 실행` 구조다.
- 파괴적 작업이나 다단계 작업을 확장하려면 `searchQuery 문자열 하나` 에 의존하는 구조에서 벗어나 `구조화된 filter + preview + approval + snapshot execution` 구조로 가야 한다.

## 검토 대상 파일

- `apps/api/app/automation.py`
- `apps/api/app/llm.py`
- `apps/api/app/graph/nodes.py`
- `apps/api/app/graph/workflow.py`
- `apps/api/app/skills/mail/implementation.py`
- `workflows/n8n/assistant-gmail-summary.json`
- `workflows/n8n/assistant-gmail-detail.json`
- `workflows/n8n/assistant-gmail-reply.json`
- `docs/gmail-integration.md`

## 현재 Gmail 조회 구조

### 1. 의도 분류

- `classify_message_intent` 가 메일 관련 요청을 `gmail_summary`, `gmail_list`, `gmail_detail`, `gmail_reply`, `gmail_thread_reply`, `gmail_draft`, `gmail_send` 등으로 분류한다.
- 조회 계열은 요약/목록/상세로 나뉘고, 쓰기 계열은 초안/발송/회신으로 분리된다.

### 2. 구조화 추출 baseline 생성

- `extract_structured_request` 는 먼저 `_extract_rule_based_request` 로 baseline extraction 을 만든다.
- Gmail 요약/목록에서는 `_build_gmail_search_query`, `_extract_gmail_list_limit`, `_extract_group_by_date`, `_extract_selected_indexes` 를 사용해 `MailExtractionPayload` 를 채운다.
- 이 단계는 규칙 기반이며 deterministic 하다.

### 3. LLM 보정 여부 결정

- `should_run_llm = baseline.intent in settings.local_llm.structured_extraction_targets` 조건으로 structured extraction LLM 호출 여부를 결정한다.
- 현재 기본 설정상 대상 intent 는 `calendar_delete`, `gmail_reply`, `gmail_thread_reply` 이다.
- 따라서 `gmail_summary`, `gmail_list`, `gmail_detail` 는 기본적으로 로컬 LLM structured extraction 대상이 아니다.

### 4. 실행 단계

- LangGraph workflow 의 `execute_skill` 노드가 skill runtime 을 통해 Gmail intent 를 실행한다.
- `gmail_summary`, `gmail_list` 는 `GmailSummarySkill` / `GmailListSkill` 을 거쳐 n8n summary webhook 으로 전달된다.
- `gmail_detail` 는 `GmailDetailSkill` 을 거쳐 detail webhook 으로 전달된다.
- `gmail_reply` 는 `GmailReplySkill` 을 거쳐 reply webhook 으로 전달된다.

> 참고: `graph/nodes.py` 에 `execute_gmail_summary`, `execute_gmail_detail`, `execute_gmail_compose`, `execute_gmail_reply` 함수가 남아 있지만, 현재 `graph/workflow.py` 의 실제 그래프에는 등록되지 않는 **데드코드** 상태다. 실행 경로 통합 분석은 이 문서 하단의 신규 섹션을 참조한다.

### 5. n8n Gmail API 호출

- summary workflow 는 Gmail node 의 `message.getAll` 로 메일 목록을 조회한다.
- detail workflow 는 후보를 찾은 뒤 상세 내용을 조합한다.
- reply workflow 는 searchQuery 또는 direct target 으로 대상 메시지를 확정한 뒤 Gmail reply operation 을 실행한다.

### 6. 응답 렌더링

- summary 결과는 `format_gmail_summary` 가 채널별 포맷으로 렌더링한다.
- detail 결과는 `format_gmail_detail` 이 렌더링한다.
- 회신/발송/초안 같은 액션 응답은 `format_gmail_action_reply` 또는 n8n reply 원문을 사용한다.

## `_build_gmail_search_query` 의 역할과 설계 방식

`_build_gmail_search_query` 는 자연어를 직접 의미 해석하는 LLM이 아니라, 자연어에서 정해진 패턴을 뽑아 Gmail native query 로 조합하는 규칙 기반 compiler 에 가깝다.

### 입력

- 사용자 원문 메시지

### 내부 처리 단계

1. 정규화
- 공백을 정리하고 lower-case 비교용 문자열을 만든다.

2. 시간 조건 생성
- `오늘`, `내일`, `이번 주`, `이번 달`, `어제`, `최근 7일`, `지난 2주`, `3월` 등을 파싱한다.
- 결과는 `after:YYYY/MM/DD`, `before:YYYY/MM/DD`, 또는 간단한 경우 `newer_than:3d` 형태로 변환된다.

3. 상태 조건 생성
- `읽지 않음`, `읽음`, `첨부`, `중요`, `별표` 를 Gmail query 조건으로 변환한다.
- 예: `is:unread`, `has:attachment`, `is:important`, `is:starred`

4. 메일함/카테고리 조건 생성
- `받은편지함`, `보낸편지함`, `초안` 등을 `in:inbox`, `in:sent`, `in:drafts` 로 변환한다.
- `프로모션`, `소셜`, `업데이트`, `포럼` 을 `category:...` 로 변환한다.

5. 필드 기반 세그먼트 추출
- `발신자`, `수신자`, `제목`, `내용`, `검색어` 같은 라벨 세그먼트를 `_extract_labeled_segment` 로 추출한다.
- 예:
  - `발신자 홍길동` -> `from:"홍길동"`
  - `수신자 test@example.com` -> `to:test@example.com`
  - `제목 주간 보고` -> `subject:"주간 보고"`
  - `내용 검토 완료` -> `"검토 완료"`

6. 보조 추론
- `홍길동이 보낸 메일` 같은 문구에서 sender 를 근사 추출한다.
- `AI 관련 메일` 같은 문구에서 keyword 를 근사 추출한다.
- 인용부호로 감싼 문구는 quoted term 으로 추가한다.

7. 중복 제거 후 join
- 동일 query part 는 한 번만 유지한다.
- 최종적으로 공백으로 join 한 Gmail q 문자열을 반환한다.

### 이 함수의 장점

- deterministic 하다.
- 테스트 가능성이 높다.
- 채널과 모델 상태에 좌우되지 않는다.
- query 생성이 빠르고 비용이 낮다.

### 이 함수의 한계

- 의미 해석의 범위가 정해진 패턴 안에만 갇혀 있다.
- `광고`, `홍보`, `뉴스레터`, `프로모션`, `마케팅 메일` 같은 동의어 확장이 빈약하다.
- 검색 의도가 구조로 남지 않고 문자열로 평탄화된다.
- `제목만`, `본문만`, `메일함 전체`, `프로모션 탭만`, `후속 삭제용 preview` 같은 고차 의도를 안정적으로 표현하기 어렵다.

## 로컬 LLM이 실제로 하는 일

### 현재 개입하는 영역

- structured extraction 보정
- baseline extraction 이 부족하거나 애매할 때 payload 를 보정
- 대표적으로 `gmail_reply`, `gmail_thread_reply` 에서 subject, sender, body, searchQuery 보정 가능

### 현재 개입하지 않는 영역

- `gmail_summary`, `gmail_list` 의 searchQuery 생성
- n8n Gmail API 호출 자체
- Gmail 목록 응답 정렬/그룹핑 로직
- bulk delete 같은 파괴적 작업 planning

### 현재 상태를 한 줄로 요약하면

- Gmail 조회는 규칙 기반 parser 주도
- Gmail 회신은 규칙 기반 baseline + 선택적 LLM 보정

## n8n Gmail 검색 API 호출이 이어지는 실제 경로

## A. Gmail summary/list 경로

1. 사용자 메시지 입력
- 예: `오늘 메일 날짜별로 10건 보여줘`

2. FastAPI rule-based extraction
- `_build_gmail_search_query` -> 예: `after:2026/03/22 before:2026/03/23`
- `_extract_gmail_list_limit` -> `10`
- `_extract_group_by_date` -> `true`

3. execution node 또는 mail skill 에서 extra payload 구성
- `searchQuery`
- `limit`
- `groupByDate`
- 필요 시 `cursor`

4. `run_n8n_automation_raw` 호출
- webhook path 는 `N8N_GMAIL_WEBHOOK_PATH`

5. n8n summary workflow 실행
- Gmail `message.getAll` 호출
- 현재 workflow 는 `labelIds=[INBOX]` 와 `q=searchQuery` 를 사용한다.

6. n8n code node 가 items 정규화
- `messageId`, `threadId`, `sender`, `subject`, `snippet`, `date`, `dateLabel`, `internalDate`, `unread`, `hasAttachments`
- `groupByDate`, `hasMore`, `nextCursor` 계산

7. FastAPI formatter 렌더링
- `format_gmail_summary` 가 WebUI/Kakao/API 채널별 텍스트를 생성한다.

## B. Gmail reply 경로

1. 사용자 메시지 입력
- 예: `제목 주간 보고 내용 확인했습니다 메일에 답장해줘`

2. baseline 추출
- `parse_gmail_reply_request` 가 subject, body, sender, thread id, message id 를 우선 추출한다.
- target direct reference 가 없으면 `_build_gmail_reply_search_query` 가 최근 30일 기반 search query 를 생성한다.

3. 선택적 local LLM structured extraction 보정
- subject 나 body 표현을 더 정제할 수 있다.
- baseline 을 보정하지만 실행은 직접 하지 않는다.

4. FastAPI -> n8n reply webhook 전달
- `message`, `reply_mode`, `subject`, `sender`, `thread_id`, `message_id`, `search_query` 등이 전달된다.

5. n8n reply workflow 실행
- direct target 이 있으면 바로 사용
- 없으면 search query 로 Gmail 검색
- 검색된 후보를 제목/발신자 일치도와 최신성으로 score 정렬
- 가장 적합한 `resolved_thread_id`, `resolved_message_id` 를 선택

6. Gmail reply 실행
- thread reply node 가 실제 회신을 보낸다.

## 현재 구조의 문제점

### 1. 조회 intent 와 작업 intent 의 모델이 분리되지 않았다.

- 조회와 변경 모두 `MailExtractionPayload` 한 타입에 많은 의미를 우겨넣는 구조다.
- 향후 bulk action 으로 가면 `selection`, `preview`, `snapshot`, `safety guard` 같은 개념이 필요해진다.

### 2. summary 와 detail workflow 가 모두 INBOX 에 고정돼 있다.

- n8n summary workflow (`assistant-gmail-summary`) 는 `labelIds=[INBOX]` 를 기본으로 건다.
- n8n detail workflow (`assistant-gmail-detail`) 도 동일하게 `labelIds=[INBOX]` 가 고정돼 있다.
- 이 상태에서는 `category:promotions` 같은 query 를 넣더라도 기대한 범위를 충분히 보지 못할 수 있다.
- 특히 광고/프로모션 정리 작업의 기반 query 로 쓰기 어렵다.
- `mailboxScope` 정책을 도입하려면 summary 와 detail 두 워크플로 모두 변경해야 한다.

### 3. cursor 가 완전한 pagination 으로 구현돼 있지 않다.

- FastAPI skill 코드는 `cursor` 를 n8n 에 전달하는 코드가 있다. (`GmailSummarySkill.execute` 에서 `extra["cursor"] = mail.cursor`)
- 하지만 summary workflow JSON 에는 **cursor 를 입력으로 받는 expression 이 없다**. 즉 보내기만 하고 쓰이지 않는 상태다.
- `nextCursor` 는 마지막 item 의 `internalDate` 를 돌려주지만, 이것은 Gmail API pagination token 이 아닌 UI 힌트 수준이다.
- cursor 를 실제로 활용하려면 n8n 쪽에서 `before:` 조건으로 query 를 좁히는 방식이 현실적인 임시 해법이다.

### 4. query 의미가 문자열 하나로 소실된다.

- `최근 30일 프로모션 메일` 도 결국 `after:... category:promotions` 문자열 하나가 된다.
- 나중에 preview, delete, archive, undo, approval 을 추가하려면 의미를 다시 역해석해야 한다.

### 5. destructive action 경로가 없다.

- 현재는 `gmail_delete`, `gmail_trash`, `gmail_archive`, `gmail_mark_read` 등의 intent, skill, workflow 가 없다.
- 따라서 `최근 30일 광고만 지워줘` 는 현재 구조에서 직접 지원 불가다.

## 예시 요구사항 검토

### 요구 예시

- `최근 30일 이내의 메일 중 광고만 지워줘`

### 현재 구조에서 어려운 이유

1. `광고` 의미 해석이 불충분
- 현재는 `프로모션`, `promotions` 정도만 직접 지원한다.
- `광고`, `홍보`, `뉴스레터`, `마케팅` 등은 별도 사전이 없다.

2. 삭제 intent 부재
- 조회는 가능해도 삭제 실행 경로가 없다.

3. preview/safety 단계 부재
- 파괴적 작업인데도 대상 개수 확인, 샘플 확인, 승인 재확인, snapshot 고정 같은 단계가 없다.

4. snapshot 없는 재검색 위험
- 승인 전 preview 와 승인 후 실행 사이에 검색 결과가 달라질 수 있다.

## 확장을 위한 목표 구조

핵심 방향은 `searchQuery 문자열 직접 생성` 중심에서 `구조화된 메일 필터 모델` 중심으로 옮기는 것이다.

### 권장 구조

1. 자연어 -> structured mail filters
2. structured filters -> Gmail native query compiler
3. query 실행 -> preview result + snapshot 생성
4. approval 후 snapshot 기반 실행

### 권장 filter 예시

```json
{
  "domain": "mail",
  "action": "trash",
  "approvalRequired": true,
  "mail": {
    "filters": {
      "mailbox": "all",
      "relativeDays": 30,
      "categories": ["promotions"],
      "sender": null,
      "recipient": null,
      "subject": null,
      "bodyKeywords": [],
      "unreadOnly": false,
      "hasAttachment": false
    },
    "selectionMode": "all",
    "previewRequired": true,
    "maxItems": 100
  }
}
```

이 구조의 장점은 아래와 같다.

- query 문자열이 아니라 의도가 구조로 남는다.
- 동의어 사전과 정책 판단을 filter 단계에서 분리할 수 있다.
- preview, approval, execution 을 각각 독립적으로 설계할 수 있다.
- 삭제, 보관, 읽음 처리, 라벨 변경 같은 작업으로 쉽게 확장된다.

## 개선 작업 제안

## 1단계. 조회 구조 정리

1. `_build_gmail_search_query` 를 유지하되 역할을 `compiler` 로 축소한다.
- 자연어를 직접 받는 대신 구조화된 filter 를 받아 query 를 빌드하는 방향이 바람직하다.

2. summary/list payload 에 `filters` 개념을 도입한다.
- `searchQuery` 는 하위 호환용으로 유지
- 신규 로직은 `filters -> compile -> searchQuery`

3. summary workflow 의 mailbox 고정 제거
- `INBOX` 고정을 옵션화
- `all`, `inbox`, `sent`, `drafts`, `category specific` 를 선택 가능하게 설계

## 2단계. 동의어 및 의미 계층 추가

1. category synonym map 도입
- `광고`, `홍보`, `프로모션`, `이벤트`, `뉴스레터`, `마케팅 메일` -> `promotions`

2. mailbox synonym map 도입
- `받은편지함`, `수신 메일`, `인박스` -> `inbox`

3. action synonym map 도입
- `지워`, `삭제`, `정리`, `휴지통`, `보관`, `읽음 처리` 등을 별도 action 으로 분기

## 3단계. destructive action 모델 추가

새로운 intent 후보:

- `gmail_trash`
- `gmail_archive`
- `gmail_mark_read`
- `gmail_mark_unread`
- `gmail_delete_permanent`

각 intent 는 아래를 가져야 한다.

- `approvalRequired=true`
- `previewRequired=true`
- `selectionMode`
- `selectedMessageIds` 또는 `snapshotId`

## 4단계. preview workflow 추가

예시:

- `assistant-gmail-search-preview`
- `assistant-gmail-bulk-trash`

preview workflow 의 역할:

- 현재 필터에 맞는 메일 수 계산
- 샘플 5건 제시
- 실행용 snapshot 생성
- 사용자에게 실제 영향 범위를 설명

응답 예시:

- `최근 30일 프로모션 메일 42건을 찾았습니다.`
- `최근 5건 예시: ...`
- `승인하면 이 42건을 휴지통으로 이동합니다.`

## 5단계. snapshot 기반 실행

삭제/보관 같은 파괴적 작업은 승인 후 재검색하지 않고 snapshot 기반으로 실행해야 한다.

필요 요소:

- `snapshotId`
- snapshot 에 포함된 `messageIds`
- snapshot 생성 시각
- snapshot expiry

이 구조가 필요한 이유:

- preview 와 execution 대상 불일치 방지
- 승인 이후 결과가 바뀌는 문제 방지
- 감사 로그 및 rollback 검토 기반 확보

## 6단계. LLM 개입 범위 재정의

향후 LLM은 아래 역할에 더 적합하다.

- 자연어를 구조화된 filters 로 정리
- 동의어와 애매한 표현 정리
- 삭제/보관 요청의 의도 확인 보조

반대로 아래 역할은 deterministic 계층에 남기는 것이 안전하다.

- Gmail query 최종 compiler
- preview 수량 계산
- message id snapshot 생성
- 실제 delete/trash/archive 실행

## 다른 자동화 도메인에 대한 사전 점검

Gmail 개선 작업에 들어가기 전에 같은 전제를 캘린더와 브라우저에도 적용해야 하는지 확인한 결과는 아래와 같다.

### 요약 결론

- 캘린더는 Gmail과 유사한 문제가 이미 있다.
- 브라우저는 현재 read-only 위주라 동일 수준의 safety 구조가 즉시 필요하지는 않다.
- 다만 브라우저가 추후 클릭, 폼 입력, 구매, 로그인, 다운로드 같은 action automation 으로 확장되면 Gmail/Calendar와 같은 승인 및 snapshot 모델이 필요하다.

## 캘린더 자동화 점검 결과

### 현재 구조

- `calendar_summary` 는 시간 범위를 rule-based 로 추출해 n8n summary webhook 에 전달한다.
- `calendar_create`, `calendar_update`, `calendar_delete` 는 승인 후 n8n Google Calendar workflow 를 직접 실행한다.
- structured extraction LLM 대상은 현재 기본 설정상 `calendar_delete` 만 포함된다.

### Gmail과 비슷한 부분

1. 일부 destructive action 이 단일 검색 결과에 바로 의존한다.
- `assistant-calendar-update` 와 `assistant-calendar-delete` workflow 는 `getAll limit=1` 로 첫 번째 매칭 이벤트만 사용한다.
- 즉 후보가 여러 개인 경우에도 preview 없이 첫 결과를 바로 변경/삭제한다.

2. 승인 전 preview 단계가 없다.
- 현재는 승인 티켓은 있지만, 승인 전에 `실제로 어떤 이벤트가 선택될지` 를 사용자에게 검토시키는 단계가 없다.
- 이는 Gmail의 미래 bulk delete 와 같은 계열의 문제다.

3. canonical target model 이 없다.
- 현재는 `search_title`, `search_time_min`, `search_time_max` 조합으로 후보를 찾는다.
- 이후 실행 대상은 event id 로 고정되지 않고, workflow 내 검색 결과에 따라 결정된다.

4. snapshot execution 이 없다.
- 승인 시점과 실제 실행 시점 사이에 캘린더 상태가 바뀌면 다른 이벤트가 선택될 수 있다.

### 캘린더에서 먼저 보강해야 할 점

1. `calendar_update` 와 `calendar_delete` 에 preview-first 모델 도입 검토
- 예: `이 일정을 삭제할까요?` 와 함께 실제 제목, 시작 시간, event_id 를 먼저 보여주는 방식

2. 검색 결과가 2건 이상이면 단일 선택 강제
- 자동 선택보다 후보 제시가 안전하다.

3. 승인 payload 에 event snapshot 포함 검토
- 승인 후 재검색 대신 event id 기준 실행

4. `calendar_create` 는 현재 구조 유지 가능
- create 는 대상 탐색보다 입력 completeness 가 중요하므로 Gmail delete 만큼의 구조 변경은 당장 필요하지 않다.

### 캘린더에 대한 판단

- Gmail 개선과 별개로 `calendar_update/delete` 는 같은 safety 원칙을 적용해야 한다.
- 특히 preview + approval + target snapshot 구조는 캘린더에도 공통 정책으로 두는 것이 맞다.

## 브라우저 자동화 점검 결과

### 현재 구조

- `browser_read`, `browser_screenshot`, `browser_search` 는 rule-based 로 URL 또는 query 만 추출한다.
- 실행은 n8n 이 아니라 `browser-runner` HTTP API 로 바로 전달된다.
- browser-runner 는 Playwright 기반이며 URL 검증, timeout, 결과 길이 제한 등을 수행한다.

### 현재 단계에서 Gmail과 다른 점

1. 현재 기능이 모두 사실상 read-only 이다.
- 페이지 읽기
- 스크린샷
- 검색 결과 수집

2. 외부 상태를 변경하지 않는다.
- 클릭, 입력, 제출, 구매, 로그인, 삭제 같은 action 이 아직 없다.

3. approval 필요성이 낮다.
- 지금 범위에서는 destructive action 위험이 상대적으로 적다.

### 브라우저에서 이미 보이는 구조적 한계

1. structured extraction 이 단순하다.
- URL, query 정도만 추출한다.
- 향후 복합 브라우저 작업에는 단계적 action plan 모델이 필요하다.

2. result context 저장이 얕다.
- 현재는 `browser_result` 를 반환하지만, 후속 액션에서 `방금 본 페이지`, `첫 번째 검색 결과`, `그 사이트에서 더 찾아줘` 같은 문맥을 정교하게 잇는 구조는 약하다.

3. snapshot 개념이 없다.
- 현재는 read-only 라 문제되지 않지만, action automation 으로 가면 검색 결과나 현재 URL 상태를 snapshot 으로 고정해야 한다.

### 브라우저에 대한 판단

- 현재 `browser_read/search/screenshot` 범위에서는 Gmail/Calendar 수준의 approval-first 구조가 필수는 아니다.
- 하지만 아래 기능이 추가되면 같은 원칙을 적용해야 한다.
  - 검색 결과 중 특정 링크 자동 열기
  - 사이트 내 버튼 클릭
  - 폼 자동 입력 및 제출
  - 로그인 세션이 필요한 작업
  - 파일 다운로드 또는 업로드
  - 구매/예약/전송 같은 외부 상태 변경

### 브라우저의 후속 설계 방향

- read-only browser skill 과 action browser skill 을 명확히 분리
- action skill 에만 approvalRequired 기본 적용
- DOM 대상 선택 또는 검색 결과 선택 시 snapshot 또는 selector pinning 모델 도입

## 1, 2, 3 작업 전에 반영할 공통 원칙

이 문서 기준으로 다음 작업을 진행할 때 공통 정책을 먼저 깔고 가는 것이 좋다.

1. canonical model 우선
- 자연어를 바로 executor payload 로 만들지 않는다.
- 중간에 canonical filter 또는 target model 을 둔다.

2. read-only 와 mutation/action 을 구조적으로 분리
- Gmail, Calendar, Browser 모두 같은 기준으로 나눈다.

3. ambiguous target 은 preview-first
- 검색 결과 다수일 때 자동 선택보다 후보 제시를 우선한다.

4. destructive action 은 snapshot execution
- 승인 후 재검색하지 않고 고정된 target id 로 실행한다.

5. LLM은 planner, deterministic layer 는 executor
- LLM이 최종 삭제/변경 대상을 임의로 확정하지 않게 한다.

## 추천 아키텍처 원칙

### 원칙 1. LLM은 planner, 실행기는 아니다.

- LLM은 해석과 구조화에만 사용한다.
- 실행은 Python/n8n 의 deterministic layer 가 맡는다.

### 원칙 2. Gmail native query 는 중간 산출물이다.

- 시스템 내부의 canonical representation 은 structured filters 여야 한다.
- query string 은 Gmail API 호환을 위한 파생 값이어야 한다.

### 원칙 3. destructive action 은 항상 2단계다.

- preview
- approval
- snapshot execution

### 원칙 4. list/detail/action 의 session context 를 분리 저장한다.

현재 `last_candidates` 중심 구조만으로는 충분하지 않다.

추가 권장 상태:

- `last_mail_filters`
- `last_mail_query`
- `last_mail_items`
- `last_mail_snapshot_id`
- `last_selected_message_ids`
- `last_selected_thread_id`

## 바로 추진 가능한 작업

0. graph/nodes.py 데드코드 제거
- `execute_gmail_summary`, `execute_gmail_detail`, `execute_gmail_compose`, `execute_gmail_reply`, `execute_calendar_summary`, `execute_calendar_write`, `_build_mail_result_context`, `_build_calendar_n8n_failure_reply` 삭제
- `graph/workflow.py` docstring 을 현행 구조에 맞게 갱신
- 기능 영향 없이 즉시 가능

1. 리팩터링 전 테스트 케이스 선행 추가
- 현재 6개뿐인 `GmailSearchQueryTests` 에 동의어·상태·시간 조건 케이스 추가
- 리팩터링 후 backwards compatibility 검증 기준선 확보

2. Gmail filter schema 초안 정의
- `MailExtractionPayload` 확장 또는 `MailActionPayload` 분리

3. `_build_gmail_search_query` 리팩터링 초안 작성
- 자연어 직접 입력 대신 structured filters compiler 로 재배치

4. `assistant-gmail-summary` 및 `assistant-gmail-detail` workflow 의 mailbox 제약 점검
- `INBOX` 고정이 유지돼야 하는지 검토
- 필요 시 `mailboxScope` 기반 옵션화

위 항목의 구체 설계 초안은 아래 문서에 정리했다.

- `docs/quality-and-scalability/2026-03-22-gmail-filter-schema-query-compiler-design.md`

5. `gmail_trash` preview-first 설계 문서 작성
- 승인 플로우까지 포함한 end-to-end 설계

## 후속 검토 질문

다음 검토에서는 아래를 먼저 결정하는 것이 좋다.

1. `광고` 를 `category:promotions` 로 단순 매핑할지, 별도 synonym policy 를 둘지
2. bulk delete 의 최대 허용 건수를 몇 건으로 제한할지
3. preview snapshot 을 어디에 저장할지
- Redis
- DB
- approval ticket payload
4. n8n Gmail node 로 충분한지, Gmail REST API 직접 호출이 필요한지
5. rollback 또는 undo 요구 수준이 필요한지

## 실행 경로 이중화 분석 및 통합 방향

### 현재 상태: skill 경로와 graph 노드 경로의 이중화

현재 Gmail 실행 관련 코드가 두 곳에 존재한다.

| 위치 | 함수 | 현재 사용 여부 |
|------|------|----------------|
| `graph/nodes.py` | `execute_gmail_summary` | **미사용 (데드코드)** |
| `graph/nodes.py` | `execute_gmail_detail` | **미사용 (데드코드)** |
| `graph/nodes.py` | `execute_gmail_compose` | **미사용 (데드코드)** |
| `graph/nodes.py` | `execute_gmail_reply` | **미사용 (데드코드)** |
| `graph/nodes.py` | `execute_calendar_summary` | **미사용 (데드코드)** |
| `graph/nodes.py` | `execute_calendar_write` | **미사용 (데드코드)** |
| `graph/nodes.py` | `_build_mail_result_context` | **미사용 (데드코드)** |
| `skills/mail/implementation.py` | `GmailSummarySkill.execute` 등 | **활성** |
| `automation.py` | `_build_mail_result_context` | **활성** |
| `automation.py` | `_merge_mail_request_context` | **활성** |

### 근거

`graph/workflow.py` 의 `build_assistant_graph()` 를 보면 실제 등록된 노드는 아래 7개뿐이다.

- `classify`
- `validate`
- `check_approval_skill`
- `execute_skill`
- `execute_web_search`
- `execute_mcp_tool`
- `execute_chat`

Gmail 과 Calendar intent 는 모두 `_route_after_validate` 에서 `get_skill_runtime(intent)` 을 확인한 뒤 skill 이 있으면 `"execute_skill"` 또는 `"check_approval_skill"` 로 분기한다. 즉 `execute_gmail_summary`, `execute_gmail_detail` 같은 개별 노드 함수는 **그래프에 등록되지 않고 호출되지 않는다**.

`graph/workflow.py` 상단의 docstring 만 옛 구조를 설명하고 있어 혼동을 유발한다.

### legacy 경로 (`_process_message_legacy`)

`process_message` 에서 LangGraph workflow 실행이 실패하면 `_process_message_legacy` 로 fallback 한다. 이 경로도 `_execute_registered_skill` → skill runtime 을 사용하므로, **레거시 경로 역시 skill 실행 경로와 동일**하다.

### `_build_mail_result_context` 중복

동일한 함수가 `automation.py` (line 603)과 `graph/nodes.py` (line 19) 두 곳에 정의돼 있다.

- skill 경로는 `automation.py` 의 함수를 사용한다.
- `graph/nodes.py` 의 함수는 데드코드 `execute_gmail_summary` 등에서만 참조한다.

### 통합 방향

1. **skill 경로를 유일한 실행 경로로 확정한다.**
   - 현재 이미 skill 경로만 활성화돼 있으므로 코드 변경 없이 확정할 수 있다.

2. **데드코드를 제거한다.**
   - `graph/nodes.py` 의 `execute_gmail_summary`, `execute_gmail_detail`, `execute_gmail_compose`, `execute_gmail_reply`, `execute_calendar_summary`, `execute_calendar_write`, `_build_mail_result_context` 를 삭제한다.
   - 관련 import 가 없으므로 삭제해도 다른 모듈에 영향 없다.

3. **`graph/workflow.py` docstring 을 현행 구조에 맞게 수정한다.**
   - 옛 개별 노드 라우팅 설명을 제거하고, 현재의 `execute_skill` 통합 구조를 반영한다.

4. **향후 리팩터링 시 변경 지점을 skill 경로 한 곳으로 제한한다.**
   - `filters → compile → searchQuery` 변환은 skill 내부에서만 다루면 된다.
   - `mailboxScope` 정책도 skill 의 `execute` 에서 extra_payload 에 넣는다.

### 데드코드 제거 대상 요약

```
graph/nodes.py:
  - _build_mail_result_context()        (데드코드, automation.py 에 동일 함수 존재)
  - _build_calendar_n8n_failure_reply()  (데드코드 전용 helper)
  - execute_calendar_summary()           (데드코드)
  - execute_calendar_write()             (데드코드)
  - execute_gmail_compose()              (데드코드)
  - execute_gmail_reply()                (데드코드)
  - execute_gmail_summary()              (데드코드)
  - execute_gmail_detail()               (데드코드)

graph/workflow.py:
  - docstring: 옛 개별 노드 라우팅 설명 업데이트 필요
```

### 제거 후 기대 효과

- Gmail/Calendar 실행 로직이 skill 한 곳에서만 유지보수된다.
- `filters`, `mailboxScope`, `cursor` 같은 신규 필드 도입 시 변경 지점이 절반으로 줄어든다.
- `_build_mail_result_context` 중복이 사라져 result context 확장이 일관적이다.
- 신규 개발자가 코드를 읽을 때 혼동이 줄어든다.

## 코드 검증 기반 추가 보강 사항

코드를 대조 검증한 결과 기존 문서에서 누락되었거나 보강이 필요한 항목을 아래 정리한다.

### 추가 사항 1. detail 워크플로도 INBOX 고정

- `assistant-gmail-detail.json` 의 `Find Gmail Message` 노드도 `labelIds=[INBOX]` 가 고정이다.
- 문서 본문의 `현재 구조의 문제점` 2번을 summary + detail 모두 포함하도록 수정 반영했다.

### 추가 사항 2. 동의어 설계에 mailbox·state 계열 누락

설계 문서의 2단계는 category synonym map 만 강조한다. 하지만 현재 코드에는 아래 하드코딩도 존재한다.

- **state 동의어**: `"읽지 않"`, `"안 읽"`, `"unread"` → `is:unread` / `"첨부"`, `"attachment"` → `has:attachment`
- **mailbox 동의어**: `"보낸편지함"`, `"보낸 메일"`, `"sent mail"` → `in:sent` / `"초안"`, `"draft"` → `in:drafts`

설계 문서에 `_normalize_mailbox_scope`, `_normalize_mail_state` 정규화 함수 및 통합 synonym table 설계를 추가해야 한다.

### 추가 사항 3. `MailExtractionPayload` 확장 시 LLM prompt 영향

`structured_extraction_targets` 에 `gmail_reply`, `gmail_thread_reply` 가 포함되어 있으므로, LLM structured extraction prompt 가 `MailExtractionPayload` 필드 이름을 참조한다. `filters`, `selection`, `safety` 필드를 추가하면 **LLM prompt와 JSON schema 도 함께 갱신**해야 한다.

### 추가 사항 4. `_extract_labeled_segment` 의 stop labels 의존관계

`_build_gmail_search_query` 는 `GMAIL_SEARCH_STOP_LABELS` 상수에 의존해서 segment extraction 을 종료한다. 이 상수의 내용에 따라 `제목 A 내용 B` 같은 복합 쿼리의 정확도가 달라진다. 리팩터링 시 stop labels 를 어떻게 유지·확장할지 결정이 필요하다.

### 추가 사항 5. `mailboxScope` 도입 시 렌더링 영향

`mailboxScope=all_mail` 또는 `sent` 가 도입되면 보낸 메일도 결과에 포함될 수 있다. 현재 `format_gmail_summary` 는 `sender - subject` 구조로만 렌더링한다. 보낸 메일에서는 recipient 이 더 중요하므로, sender/recipient 표시를 메일 방향에 따라 분기하는 방안을 검토해야 한다.

### 추가 사항 6. `filters` vs `searchQuery` 우선순위 정책

설계 문서에서 `filters` 와 기존 `searchQuery` 를 공존시키겠다고 했지만, 우선순위 규칙이 명시되어 있지 않다. 아래 정책을 확정해야 한다.

- `filters` 가 있으면 `filters → compile → searchQuery` 로 덮어쓰는가?
- `searchQuery` 가 이미 있고 `filters` 도 있으면 어떤 것이 우선인가?
- LLM 이 `searchQuery` 를 직접 수정하는 경로에서 `filters` 와의 정합성은?

권장 정책:

- `filters` 가 비어 있지 않으면 항상 `filters → compile` 결과를 `searchQuery` 로 사용한다.
- `filters` 가 없고 `searchQuery` 만 있으면 기존 호환 경로를 사용한다.
- LLM structured extraction 은 `filters` 를 채우는 방향으로 유도하되, 당분간 `searchQuery` 직접 수정도 허용한다.

### 추가 사항 7. 리팩터링 전 테스트 케이스 선행 추가 필요

현재 `GmailSearchQueryTests` 는 6개 케이스뿐이다.

- `오늘 메일 보여줘`
- `최근 메일 알려줘`
- `이번달 기준`
- `복합 필터 (제목+내용+상태+메일함)`
- `발신자+수신자`
- `필터 없으면 None`

리팩터링 전에 아래 케이스를 먼저 추가해야 동의어 정규화가 기존 결과를 깨지 않는지 검증할 수 있다.

- `프로모션 메일` → `category:promotions`
- `보낸편지함 메일` → `in:sent`
- `광고 메일` → (향후 synonym 확장 기준선)
- `어제 메일` → `after:... before:...`
- `지난 2주 메일` → `after:...`
- `읽지 않은 중요 메일` → `is:unread is:important`
- `별표 메일` → `is:starred`

## 보강 사항 요약표

| # | 항목 | 우선순위 | 반영 위치 |
|---|------|---------|----------|
| 1 | 실행 경로 통합 (데드코드 제거) | 높음 | 리뷰 + 설계 문서 |
| 2 | detail 워크플로 INBOX 고정 | 높음 | 리뷰 문서 본문 |
| 3 | `_build_mail_result_context` 중복 통합 | 높음 | 리뷰 문서 |
| 4 | mailbox·state 동의어 통합 설계 | 중간 | 설계 문서 |
| 5 | LLM prompt/schema 영향 범위 | 중간 | 설계 문서 |
| 6 | cursor 미사용 상태 명확화 | 중간 | 리뷰 문서 본문 |
| 7 | stop labels 의존관계 정리 | 낮음 | 설계 문서 |
| 8 | `mailboxScope` 도입 시 렌더링 영향 | 중간 | 설계 문서 |
| 9 | `filters` vs `searchQuery` 우선순위 정책 | 높음 | 설계 문서 |
| 10 | 리팩터링 전 테스트 케이스 선행 추가 | 높음 | 설계 문서 + 코드 |

## 최종 정리

- 현재 구조는 Gmail 읽기 기능을 빠르게 안정화하는 데에는 적절하다.
- 하지만 복합 필터와 파괴적 작업을 지원하려면 `규칙 기반 searchQuery 문자열 생성` 만으로는 한계가 분명하다.
- 실행 경로는 이미 skill 단일 경로로 수렴되어 있으며, graph/nodes.py 의 데드코드를 제거하면 유지보수 부담이 줄어든다.
- 다음 단계의 핵심은 `structured filters`, `preview-first safety`, `snapshot execution`, `LLM planner 역할 분리` 다.
- 이 방향으로 가면 `최근 30일 광고 메일 삭제`, `읽지 않은 뉴스레터 보관`, `프로모션 메일 일괄 정리` 같은 요구를 안전하게 수용할 수 있다.