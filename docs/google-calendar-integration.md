# Google Calendar 실제 연동 가이드

## 목적

이 문서는 현재 프로젝트의 `n8n` 기반 자동화 경로에 Google Calendar를 실제로 연결하는 방법을 정리한다.

현재 저장소는 아래 기준으로 준비되어 있다.

- `n8n` 편집기 로컬 접근 주소: `http://127.0.0.1:5678`
- 샘플 자동화 webhook: `http://127.0.0.1:5678/webhook/assistant-automation`
- FastAPI 내부 자동화 호출 경로: `N8N_BASE_URL=http://n8n:5678`

중요: 브라우저 접속 주소와 OAuth redirect URI는 `localhost` 가 아니라 반드시 `127.0.0.1` 로 통일한다. 두 host를 섞으면 n8n 세션 cookie와 OAuth callback host가 어긋나 `Unauthorized` 가 발생할 수 있다.

## 권장 연결 방식

개인 Google Calendar를 연결하는 경우에는 `OAuth2` 기반 `Google Calendar` credential을 `n8n`에 등록하는 방식이 가장 현실적이다.

이 방식이 적절한 이유는 아래와 같다.

- 사용자 개인 캘린더와 가장 잘 맞는다.
- `n8n` 기본 Google Calendar 노드를 그대로 사용할 수 있다.
- 이후 Gmail, Google Drive 같은 Google 계열 자동화로 확장하기 쉽다.

## 사전 준비

아래 항목은 사용자가 직접 준비해야 한다.

1. Google Cloud Project 생성
2. Google Calendar API 활성화
3. OAuth consent screen 설정
4. OAuth Client ID 생성

## Google Cloud 설정 방법

### 1. 프로젝트 생성

- Google Cloud Console에 접속한다.
- 새 프로젝트를 만든다.
- 프로젝트 이름은 예를 들어 `ai-assistant-local` 정도로 둔다.

### 2. API 활성화

- `APIs & Services` 로 이동한다.
- `Google Calendar API` 를 검색해서 활성화한다.

### 3. OAuth consent screen 설정

- `APIs & Services > OAuth consent screen` 으로 이동한다.
- External 또는 Internal 중 필요한 유형을 선택한다.
- 앱 이름, 이메일 등 필수 항목을 입력한다.
- 테스트 사용자에 본인 Google 계정을 추가한다.

### 4. OAuth Client 생성

- `APIs & Services > Credentials` 로 이동한다.
- `Create Credentials > OAuth client ID` 를 선택한다.
- 애플리케이션 유형은 `Web application` 을 선택한다.
- Authorized redirect URI 는 아래 값으로 추가한다.

```text
http://127.0.0.1:5678/rest/oauth2-credential/callback
```

- 생성 후 `Client ID` 와 `Client Secret` 을 확보한다.

## n8n에서 Google Calendar credential 생성

### 1. n8n 편집기 접속

- 브라우저에서 `http://127.0.0.1:5678` 으로 접속한다.

### 2. Credential 생성

- `Credentials` 메뉴로 이동한다.
- `Google Calendar OAuth2 API` credential을 새로 만든다.
- 위에서 발급한 `Client ID`, `Client Secret` 을 입력한다.
- 범위는 기본 캘린더 읽기부터 시작하는 것이 안전하다.

권장 시작 범위:

```text
https://www.googleapis.com/auth/calendar.readonly
```

- `Connect my account` 를 눌러 본인 Google 계정으로 로그인한다.

## 현재 저장소 기준 workflow 연결 방식

현재 샘플 workflow 파일은 [workflows/n8n/assistant-automation.json](../workflows/n8n/assistant-automation.json) 이다.

현재 상태:

- `Google Calendar OAuth2 API` credential 연결이 완료됐다.
- `assistant-automation` workflow는 실제 Google Calendar 노드로 오늘 일정을 조회한다.
- `assistant-calendar-create`, `assistant-calendar-update` workflow는 승인 후 실제 일정을 생성하거나 변경한다.
- `assistant-calendar-delete` workflow는 승인 후 실제 일정을 삭제한다.
- 현재 구현 범위에서는 일정 계열 요청을 우선 `n8n`으로 보내고, 메일과 노션 요청은 추후 별도 workflow로 확장한다.

현재 workflow 구성:

1. `Webhook` 노드에서 요청 수신
2. `Code` 노드로 오늘 날짜 범위와 timezone 계산
3. `Google Calendar` 노드로 primary calendar 기준 오늘 일정 조회
4. `Code` 노드로 일정 목록을 한국어 요약 문장으로 정리
5. `Respond to Webhook` 노드로 JSON 응답 반환

쓰기 workflow 구성:

1. 일정 생성 요청은 FastAPI에서 승인 티켓을 만든다.
2. 사용자가 `승인 <ticket_id>` 또는 승인 API로 승인한다.
3. `assistant-calendar-create` workflow가 실제 이벤트를 생성한다.
4. 일정 변경 요청도 같은 방식으로 승인 후 `assistant-calendar-update` workflow에서 처리한다.
5. 일정 삭제 요청도 같은 방식으로 승인 후 `assistant-calendar-delete` workflow에서 처리한다.

권장 응답 예시:

```json
{
  "reply": "오늘은 10시 팀 미팅, 14시 프로젝트 리뷰 일정이 있습니다.",
  "action": "calendar-summary"
}
```

## 추천 검증 순서

1. `docker compose -f infra/docker/docker-compose.yml up -d n8n` 로 `n8n`이 올라와 있는지 확인한다.
2. 브라우저에서 `http://127.0.0.1:5678` 접근이 되는지 확인한다.
3. Google Cloud에서 OAuth Client와 redirect URI를 설정한다.
4. `n8n`에서 Google Calendar credential을 생성한다.
5. `assistant-automation` workflow가 활성화되어 있는지 확인한다.
6. `오늘 일정 요약해줘` 요청을 `POST /assistant/api/chat` 또는 `POST /assistant/api/kakao/webhook` 으로 호출한다.
7. 응답 route가 `n8n` 이고 실제 일정 요약 또는 빈 일정 메시지가 반환되는지 확인한다.

## 현재 단계에서 사용자 조치가 필요한 이유

Google OAuth는 사용자 Google 계정 승인과 Google Cloud 자격 증명 발급이 필요하므로, 이 구간은 에이전트가 단독으로 완료할 수 없다.

즉, 아래 두 값은 사용자가 직접 준비해야 한다.

- Google OAuth Client ID
- Google OAuth Client Secret

이 두 값이 준비되면 이후 단계는 저장소 기준으로 바로 이어서 작업할 수 있다.

## 현재 검증 결과

- `POST /assistant/api/chat` 에서 `오늘 일정 요약해줘` 요청이 `route=n8n` 으로 처리된다.
- `POST /assistant/api/kakao/webhook` 에서도 `route=n8n` 과 `basicCard` 응답이 반환된다.
- 현재 테스트 시점에는 해당 날짜 일정이 없어 `오늘 등록된 일정이 없습니다.` 응답이 내려왔다.
- `내일 오후 3시 치과 일정 추가해줘` 요청은 승인 후 실제 캘린더 이벤트 생성까지 확인했다.
- `내일 오후 4시 치과 일정 변경해줘` 요청은 승인 후 기존 이벤트를 찾아 시간 변경까지 확인했다.
- `내일 오후 4시 치과 일정 삭제해줘` 요청은 승인 후 기존 이벤트를 찾아 삭제까지 확인 가능하도록 경로를 확장했다.