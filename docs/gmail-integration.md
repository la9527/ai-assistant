# Gmail 연동 가이드

## 현재 상태

- `assistant-gmail-summary` workflow가 추가되어 있다.
- FastAPI는 메일 관련 요청을 `N8N_GMAIL_WEBHOOK_PATH` 경로로 보낸다.
- `Gmail OAuth2 API` credential 연결이 완료됐다.
- 현재 workflow는 최근 7일 기준 받은편지함 메일 최대 5건을 읽어 제목과 발신자를 요약한다.
- `assistant-gmail-draft`, `assistant-gmail-send` workflow가 추가되어 있다.
- `assistant-gmail-reply` workflow가 추가되어 있다.
- 메일 초안 작성과 실제 발송은 승인 티켓 이후에만 실행한다.
- 메일 회신과 thread 이어쓰기도 승인 티켓 이후에만 실행한다.
- `첨부 https://...` 형태의 공용 URL 1건은 초안, 발송, 회신 경로에서 실제 첨부파일로 내려받아 포함할 수 있다.

## 현재 한계

- 현재 읽기 기능은 사실상 `assistant-gmail-summary` 단일 workflow 중심이다.
- 조회 조건은 받은편지함, 최근 기간, 최대 건수 정도만 제한적으로 다룬다.
- 응답 표현은 최근 메일 목록 요약에 최적화되어 있고, 날짜 그룹화, 더보기, 다건 선택, 본문 상세 조회는 정식 인터페이스로 분리되어 있지 않다.
- FastAPI 쪽 구조화 추출은 `searchQuery` 정도는 만들 수 있지만, `limit`, `cursor`, `detailLevel`, `groupByDate`, `selectedIndexes` 같은 읽기 파라미터는 아직 schema에 없다.
- 따라서 지금 상태는 LLM이 조회 의도를 이해해도, 실행 계층에서 그 의도를 일반화된 도구 호출로 옮기기 어렵다.

## 목표 구조

메일 읽기 기능은 `요약 1개`가 아니라 아래 3개 읽기 도구로 분리하는 방향을 기본안으로 둔다.

1. `gmail_list`
	- 역할: 메일 목록 조회
	- 예시: `오늘 온 메일 20건 보여줘`, `지난주 메일을 날짜별로 나눠서 보여줘`, `읽지 않은 메일만 더 보여줘`
2. `gmail_detail`
	- 역할: 특정 메일 상세 조회
	- 예시: `3번 메일 자세히 보여줘`, `첫 번째 항목 본문만 알려줘`, `방금 메일 헤더까지 보여줘`
3. `gmail_thread`
	- 역할: 특정 메일 스레드 조회
	- 예시: `이 메일 대화 전체 보여줘`, `2번 메일 스레드 흐름 요약해줘`

핵심 원칙은 아래와 같다.

- LLM은 `무슨 읽기 도구를 어떤 파라미터로 호출할지` 판단한다.
- 실제 Gmail API 호출과 응답 정규화는 n8n이 맡는다.
- FastAPI/LangGraph는 구조화 추출, 세션 상태, 후속 참조 연결을 담당한다.
- 채널별 표현은 WebUI와 Kakao 특성에 맞게 별도로 렌더링한다.

## 권장 파라미터 설계

### 1. `gmail_list`

- `searchQuery`: Gmail query string
- `labelIds`: 기본값 `INBOX`
- `limit`: 기본 10, 최대 20 또는 30
- `cursor`: 다음 페이지 조회용 토큰
- `groupByDate`: 날짜별 그룹화 여부
- `includeSnippet`: 미리보기 포함 여부
- `unreadOnly`: 읽지 않음 필터
- `sender`: 발신자 조건
- `subject`: 제목 키워드

### 2. `gmail_detail`

- `messageId`: 대상 메일 ID
- `threadId`: 필요 시 스레드 ID
- `detailLevel`: `brief`, `full`
- `includeBody`: 본문 포함 여부
- `includeHeaders`: 헤더 포함 여부
- `includeAttachments`: 첨부 메타데이터 포함 여부

### 3. `gmail_thread`

- `threadId`: 대상 스레드 ID
- `maxMessages`: 최대 포함 메시지 수
- `summarize`: 스레드 요약 여부

## 세션 상태 확장 기준

기존 `last_candidates` 만으로는 `더보기`, `3번과 5번 선택`, `어제 그룹만 다시`, `이 메일 상세`, `같은 스레드 보여줘` 같은 후속 요청을 안정적으로 처리하기 어렵다. 메일 읽기 확장 시 아래 구조를 세션 상태에 저장하는 것을 권장한다.

- `last_mail_query`: 마지막 Gmail 검색 조건
- `last_mail_items`: 마지막 목록 결과
- `last_mail_cursor`: 다음 페이지 조회용 cursor
- `last_mail_grouping`: 날짜 그룹화 여부
- `last_selected_message_ids`: 사용자가 선택한 메시지 ID 목록
- `last_selected_thread_id`: 최근 선택 스레드 ID

각 목록 item에는 최소한 아래 필드가 포함되어야 한다.

- `messageId`
- `threadId`
- `internalDate` 또는 정규화된 날짜 문자열
- `sender`
- `subject`
- `snippet`
- `unread`
- `hasAttachments`

## 채널별 표현 기준

### WebUI

- 날짜 헤더를 기준으로 그룹화한다. 예: `오늘`, `어제`, `2026-03-18 수요일`
- 각 메일은 번호, 보낸 사람, 제목, 1줄 미리보기, 수신 시각을 표시한다.
- 상세 조회, 스레드 조회, 답장 초안 작성 같은 후속 액션을 붙이기 쉬운 형태를 유지한다.

### Kakao

- 길이가 긴 본문은 한 번에 모두 내려주지 않는다.
- 기본은 compact 목록 + `quickReplies` 중심으로 구성한다.
- 예: `1번 상세`, `더보기`, `오늘만`, `이번 주`, `읽지 않음만`
- 자동화 응답은 `basicCard` 와 `quickReplies` 위주로 유지한다.

## n8n workflow 권장 재구성

현재 `assistant-gmail-summary` workflow는 향후 아래 방향 중 하나로 정리한다.

1. `assistant-gmail-summary` 를 `assistant-gmail-list` 성격으로 일반화
2. 또는 아래 3개 workflow로 분리
	- `assistant-gmail-list`
	- `assistant-gmail-detail`
	- `assistant-gmail-thread`

권장안은 2번이다. 이유는 다음과 같다.

- 목록 조회와 상세 조회는 응답 구조가 다르다.
- 스레드 조회는 thread 중심 처리와 요약 로직이 별도로 필요하다.
- 승인 불필요한 읽기 전용 기능끼리도 입력 schema가 다르므로 workflow를 분리하는 편이 유지보수에 유리하다.

## FastAPI/LangGraph 작업 기준

메일 읽기 확장을 위해 아래 변경이 필요하다.

1. `mail` payload schema 확장
	- `limit`, `cursor`, `groupByDate`, `detailLevel`, `selectedIndexes` 추가
2. 읽기 intent 분리
	- `gmail_summary` 유지
	- 내부적으로는 `gmail_list`, `gmail_detail`, `gmail_thread` 로 점진 분리
3. 세션 상태 확장
	- `last_candidates` 중심 저장에서 `last_mail_result_context` 저장으로 확장
4. 후속 참조 해석 강화
	- `첫 번째`, `3번과 5번`, `더보기`, `같은 메일`, `이 스레드` 해석
5. 채널별 렌더러 분리
	- WebUI: Markdown 중심
	- Kakao: compact + quickReplies 중심

## 단계별 작업안

### 1단계. 목록 조회 일반화

- `assistant-gmail-summary` workflow가 `searchQuery`, `limit`, `cursor`, `groupByDate` 를 받도록 확장한다.
- 응답 items에 `messageId`, `threadId`, `internalDate`, `unread`, `hasAttachments` 를 추가한다.
- WebUI 렌더러는 날짜 그룹 표시를 지원한다.
- 기존 `gmail_summary` 요청은 하위 호환으로 유지한다.

### 2단계. 상세 조회 도입

- `gmail_detail` intent 와 n8n workflow를 추가한다.
- 목록 item 선택 후 `messageId` 기반 상세 조회를 수행한다.
- 기본 응답은 `brief`, 필요 시 `full` 본문까지 확장한다.

### 3단계. 다건 선택과 더보기

- `selectedIndexes` 와 `cursor` 기반 후속 요청을 지원한다.
- 예: `1번과 3번 자세히`, `다음 10건 더 보여줘`
- 세션 상태에 마지막 검색 컨텍스트를 저장한다.

### 4단계. 스레드 조회와 요약

- `gmail_thread` intent 와 workflow를 추가한다.
- `이 메일 대화 전체`, `같은 스레드 요약` 같은 요청을 처리한다.

### 5단계. 채널 UX 보강

- Kakao `quickReplies` 를 메일 조회 후속 액션과 연결한다.
- Open WebUI에서는 읽기 전용 액션 버튼 또는 명령 제안 형태를 검토한다.

## 권장 구현 순서

- 1순위: `gmail_list` 확장
- 2순위: `gmail_detail` 추가
- 3순위: 세션 상태에 mail result context 저장
- 4순위: `gmail_thread` 추가
- 5순위: Kakao/WebUI 채널별 UX 보강

이 순서를 권장하는 이유는 `상세 보기`, `날짜별 구분`, `다건 조회`, `더보기` 모두가 결국 `일반화된 목록 조회 결과` 위에서 동작하기 때문이다.

## 현재 응답 동작

`최근 메일 요약해줘` 요청을 보내면 현재는 아래 성격의 응답을 반환한다.

- Gmail 자동화 경로는 `route=n8n` 으로 처리된다.
- 최근 7일 이내 받은편지함 메일이 있으면 발신자와 제목 기준 요약이 내려온다.
- 메일이 없으면 빈 메일함 안내 문구를 반환한다.

`test@example.com로 제목 주간 보고, 내용 오늘 작업 완료 메일 초안 작성해줘` 또는 `... 메일 보내줘` 요청을 보내면 아래 동작을 한다.

- 먼저 승인 티켓을 만든다.
- 사용자가 `승인 <ticket_id>` 또는 승인 API를 호출하면 n8n Gmail workflow가 실행된다.
- 초안 요청은 Gmail Draft에 저장하고, 발송 요청은 실제 메일을 보낸다.
- `받는 사람`, `수신`, `참조`, `숨은 참조` 같은 한국어 라벨과 여러 이메일 주소도 함께 파싱한다.
- Kakao 채널에서는 승인 카드와 함께 승인/거절 quick reply가 바로 제공된다.
- Kakao quick reply와 카드 버튼에는 `첨부 https://...` 형식이 포함된 메일 초안, 메일 회신 예시도 함께 노출된다.

`제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘` 또는 `thread 18cc... 내용 후속 안내입니다 메일 이어서 보내줘` 요청을 보내면 아래 동작을 한다.

- 먼저 승인 티켓을 만든다.
- 제목이나 `thread id`, `message id`, `발신자` 정보를 바탕으로 최근 30일 메일에서 대상을 찾는다.
- 회신 대상이 여러 건이면 제목과 발신자 일치도를 기준으로 가장 적합한 최근 메시지를 우선 선택한다.
- 일반 답장은 `replyToSenderOnly=true` 로 회신하고, thread 이어쓰기는 기존 수신자 목록을 유지해 후속 메시지를 보낸다.

## 실제 연결 방법

1. `n8n` 편집기 `http://127.0.0.1:5678` 에 접속한다.
2. `Credentials` 메뉴에서 `Gmail OAuth2 API` credential을 생성한다.
3. Google Cloud Console에서 Gmail API를 활성화한다.
4. OAuth Client redirect URI를 `http://127.0.0.1:5678/rest/oauth2-credential/callback` 로 맞춘다.
5. Gmail credential 연결 후 `assistant-gmail-summary` workflow가 `gmailOAuth2` credential을 사용하는지 확인한다.

주의: 브라우저에서 `localhost:5678` 로 열고 redirect URI를 `127.0.0.1:5678` 로 등록하는 식으로 host를 섞으면 OAuth callback 이후 `Unauthorized` 가 발생할 수 있다. 접속 주소와 redirect URI를 둘 다 `127.0.0.1` 기준으로 유지한다.

주의: n8n에서 Gmail credential을 삭제 후 다시 만들면 credential 이름이 같아도 내부 ID는 바뀐다. 이 경우 저장소의 Gmail workflow JSON 과 live n8n workflow 가 예전 credential ID를 계속 참조할 수 있으므로, workflow를 다시 import 하고 publish 해야 실제 실행 경로가 새 credential을 사용한다.

## 다음 권장 작업

- 현재 workflow는 최근 메일 5건 제목과 발신자 요약, 메일 초안 작성, 실제 발송, 메일 회신, thread 이어쓰기까지 구현되어 있다.
- 읽기 기능은 `요약 1개` 확장에서 멈추지 말고 `gmail_list`, `gmail_detail`, `gmail_thread` 중심 구조로 재편하는 것을 다음 우선순위로 둔다.
- 첫 구현은 `gmail_list` 확장과 `gmail_detail` 추가를 최소 범위로 진행하는 것을 권장한다.

## 현재 검증 기준

- `POST /assistant/api/chat` 에서 `최근 메일 요약해줘` 요청이 `route=n8n` 으로 처리되어야 한다.
- 응답은 최근 메일 목록 요약 또는 빈 메일함 안내 문구여야 한다.
- `POST /assistant/api/chat` 에서 메일 초안 또는 발송 요청은 먼저 `route=approval_required` 로 처리되어야 한다.
- 승인 후에는 초안 작성 또는 실제 발송 완료 문구가 반환되어야 한다.
- `POST /assistant/api/chat` 에서 메일 회신 또는 thread 이어쓰기 요청도 먼저 `route=approval_required` 로 처리되어야 한다.
- 승인 후에는 회신 실행 완료 문구가 반환되어야 한다.