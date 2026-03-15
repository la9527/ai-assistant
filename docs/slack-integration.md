# Slack 연동 가이드

## 현재 상태

- FastAPI는 `POST /assistant/api/slack/events` 경로에서 Slack Events API 요청을 받는다.
- 현재 구현 범위는 `url_verification`, Slack 서명 검증, DM 또는 `app_mention` 메시지 처리, 승인 명령 처리, Bot token 기반 응답 전송이다.
- 로컬 payload 기준으로 `app_mention`, DM, 승인 필요 응답 경로까지 검증했다.
- 공개 HTTPS 엔드포인트는 준비되었고 `https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/events` 기준 `url_verification` 과 대표 `app_mention` payload 응답까지 확인했다.
- 현재 실환경 Slack 워크스페이스 검증의 남은 조건은 `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` 설정과 실제 앱 설치다.

## 필요한 환경변수

`.env` 또는 배포 환경에 아래 값을 넣는다.

- `SLACK_BOT_TOKEN=xoxb-...`
- `SLACK_SIGNING_SECRET=...`
- `SLACK_APP_TOKEN=`

참고:

- 현재 구현은 `Events API` 기준이므로 `SLACK_APP_TOKEN`은 필수는 아니다.
- 나중에 `Socket Mode`를 병행하거나 Slack Bolt 기반 worker를 붙일 때만 `SLACK_APP_TOKEN`이 필요하다.

환경변수를 수정한 뒤에는 아래 명령으로 API를 다시 빌드한다.

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --build api
```

## Slack 앱 생성 절차

1. Slack API 페이지 `https://api.slack.com/apps` 에서 새 앱을 만든다.
2. `From scratch` 로 생성하고 대상 워크스페이스를 선택한다.
3. 앱 이름은 예를 들어 `AI Assistant` 로 둔다.

## Bot Token 설정

1. Slack 앱 설정의 `OAuth & Permissions` 로 이동한다.
2. 아래 Bot Token Scopes를 추가한다.
3. 워크스페이스에 앱을 설치한다.
4. 발급된 `Bot User OAuth Token` 값을 `SLACK_BOT_TOKEN` 에 넣는다.

권장 Bot Token Scopes:

- `app_mentions:read`
- `chat:write`
- `im:history`

선택 Scope:

- `chat:write.public`
설명: 앱이 초대되지 않은 공개 채널에도 쓰려는 경우만 추가한다.

## Signing Secret 설정

1. Slack 앱 설정의 `Basic Information` 으로 이동한다.
2. `App Credentials` 영역에서 `Signing Secret` 값을 확인한다.
3. 이 값을 `SLACK_SIGNING_SECRET` 에 넣는다.

## Events API 설정

1. Slack 앱 설정의 `Event Subscriptions` 로 이동한다.
2. `Enable Events` 를 켠다.
3. `Request URL` 에 아래 경로를 넣는다.

```text
https://<your-domain>/assistant/api/slack/events
```

예시:

```text
https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/events
```

권장 입력은 위 경로 그대로이며 끝에 `/` 를 붙이지 않는 형식이다. 다만 현재 서버는 `/assistant/api/slack/events/` 도 함께 처리하도록 보완되어 있어 trailing slash 때문에 `url_verification` 이 실패하지 않도록 수정된 상태다.

4. URL 검증이 통과하면 Bot Events를 추가한다.

필수 Bot Events:

- `app_mention`
- `message.im`

주의:

- 현재 공개 채널에서는 `app_mention` 이벤트만 처리한다.
- DM은 `message.im` 이벤트를 사용한다.
- 서명 검증을 쓰므로 Slack이 보내는 실제 요청만 통과한다.

## Slack 앱 설정에서 추가로 확인할 항목

### App Home

- `Messages Tab` 을 켜 두면 DM 테스트가 쉬워진다.

### Event 대상 채널

- 공개 채널 테스트는 앱을 채널에 초대한 뒤 `@앱이름 질문` 형식으로 보낸다.
- DM 테스트는 Slack 앱 홈 또는 직접 메시지 창에서 보낸다.

## 현재 동작 방식

### 공개 채널

- `@AI Assistant 최근 메일 요약해줘`
- `@AI Assistant 오늘 일정 요약해줘`
- `@AI Assistant 승인 <ticket_id>`

### DM

- `최근 메일 요약해줘`
- `la9527@daum.net로 제목 테스트 내용 본문입니다 메일 초안 작성해줘`
- `승인 <ticket_id>`

현재 Slack 응답 방식:

- 요청을 받으면 세션을 `channel=slack` 으로 저장한다.
- 승인 필요 작업이면 `approval_ticket_id` 를 생성한다.
- `SLACK_BOT_TOKEN` 이 있으면 `chat.postMessage` 로 같은 채널에 결과를 다시 보낸다.
- 토큰이 없으면 API는 처리하지만 Slack 메시지 전송은 `delivery=not_configured` 상태로 남는다.

## 실환경 검증 절차

1. `.env` 에 `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` 를 넣는다.
2. API를 재빌드한다.
3. Slack 앱의 `Event Subscriptions` 에 `https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/events` 를 저장한다.
4. 앱을 워크스페이스에 설치한다.
5. 앱을 테스트할 채널에 초대한다.
6. 아래 순서로 실제 메시지를 보낸다.

검증 순서:

1. 공개 채널에서 `@앱이름 최근 메일 요약해줘`
2. DM에서 `오늘 일정 요약해줘`
3. DM에서 `la9527@daum.net로 제목 슬랙 테스트 내용 본문입니다 메일 초안 작성해줘`
4. 이어서 `승인 <ticket_id>`

성공 기준:

- Slack 채널 또는 DM에 응답 메시지가 도착한다.
- 승인 필요 요청은 승인 전 안내 문구와 ticket id가 포함된다.
- 승인 후에는 `route=n8n` 기반 실행 결과가 도착한다.

현재 보류 메모:

- 공개 엔드포인트와 `url_verification` 응답은 준비됐다.
- 현재는 Slack 앱 토큰과 signing secret이 비어 있어서 실제 워크스페이스 메시지 송수신 검증만 남아 있다.

## 장애 점검 포인트

### URL verification 실패

- `Request URL` 경로가 `/assistant/api/slack/events` 인지 확인한다.
- 과거에는 끝에 `/` 가 붙으면 리다이렉트가 발생해 Slack 검증이 실패할 수 있었지만, 현재는 `/assistant/api/slack/events/` 도 직접 처리하도록 수정됐다.
- reverse proxy가 Slack 요청을 API 컨테이너로 넘기는지 확인한다.
- HTTPS 인증서가 정상인지 확인한다.

### 401 invalid slack signature

- `SLACK_SIGNING_SECRET` 값이 Slack 앱의 `Signing Secret` 과 같은지 확인한다.
- API 재빌드를 했는지 확인한다.

### 응답은 되는데 Slack에 메시지가 안 보임

- `SLACK_BOT_TOKEN` 값이 비어 있지 않은지 확인한다.
- `chat:write` scope가 있는지 확인한다.
- 앱이 해당 채널에 초대됐는지 확인한다.

### DM은 되는데 채널 mention이 안 됨

- `app_mention` Bot Event가 등록됐는지 확인한다.
- 채널에 앱이 초대됐는지 확인한다.

## 현재 남은 Slack 작업

- 공개 도메인 준비 후 실제 워크스페이스 토큰 연결 검증
- 필요 시 Slack Block Kit 응답 포맷 추가
- 필요 시 채널별 응답 길이 제한과 후속 스레드 응답 정책 추가