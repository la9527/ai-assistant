# Slack 연동 가이드

## 현재 상태

- FastAPI는 `POST /assistant/api/slack/events` 경로에서 Slack Events API 요청을 받는다.
- FastAPI는 `POST /assistant/api/slack/interactions` 경로에서 Slack Block Kit 버튼 인터랙션 요청을 받는다.
- 현재 구현 범위는 `url_verification`, Slack 서명 검증, DM 또는 `app_mention` 메시지 처리, 3초 이내 ACK 후 백그라운드 작업, 승인 명령 처리, 승인 버튼 처리, Bot token 기반 후속 응답 전송이다.
 서명된 테스트 payload 기준으로 DM ACK, 백그라운드 후속 처리, 승인 버튼 인터랙션 ACK와 후속 승인 처리까지 검증했다.
 최근 로컬 ingress 기준 검증에서는 `messages` 와 `state` API에 Slack 원문, `approval_required`, `승인 <ticket_id>`, 최종 `route=n8n` 결과까지 순서대로 저장되는 것을 확인했다.
- 공개 HTTPS 엔드포인트는 준비되었고 `https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/events` 기준 `url_verification` 과 대표 `app_mention` payload 응답까지 확인했다.
 현재 보류 메모:

 실제 워크스페이스 설치 전에는 Slack API 응답 전송이 `delivery=not_configured` 또는 `channel_not_found` 같은 권한 오류일 수 있다.

실제 적용은 아래 순서대로 진행하는 편이 가장 안전하다.

1. Slack 앱을 만들고 Bot Token Scope를 먼저 확정한다.
2. `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` 를 `.env` 에 넣는다.
3. API를 재빌드해 최신 설정을 반영한다.
4. Slack 앱의 `Event Subscriptions` 에 `/assistant/api/slack/events` 를 등록하고 `url_verification` 통과를 확인한다.
5. Bot Events 에 `app_mention`, `message.im` 을 추가하고, `ai비서` 채널을 무멘션으로 쓸 경우 `message.channels` 도 반드시 추가한다.
6. Slack 앱의 `Interactivity & Shortcuts` 에 `/assistant/api/slack/interactions` 를 등록한다.
7. 앱을 워크스페이스에 설치하고, 테스트할 채널에 초대한다.
8. 공개 채널 `app_mention`, DM, 승인 필요 요청, 승인 버튼 순서로 실제 테스트한다.
9. API 로그에서 접수 ACK, 백그라운드 처리, 후속 스레드 응답, 버튼 인터랙션 처리까지 함께 확인한다.

권장 검증 순서는 아래와 같다.

1. 공개 채널에서 `@앱이름 오늘 일정 요약해줘`
2. DM에서 `최근 메일 요약해줘`
3. DM에서 승인 필요한 요청을 보낸다.
4. 생성된 응답의 `승인`, `거절` 버튼을 눌러 승인 흐름을 확인한다.
5. 마지막으로 텍스트 명령 `승인 <ticket_id>` 도 fallback 용도로 확인한다.

## 필요한 환경변수

`.env` 또는 배포 환경에 아래 값을 넣는다.

- `SLACK_BOT_TOKEN=xoxb-...`
- `SLACK_SIGNING_SECRET=...`
- `SLACK_APP_TOKEN=`
- `SLACK_AUTO_RESPONSE_CHANNELS=ai비서`

참고:

- 현재 구현은 `Events API` 기준이므로 `SLACK_APP_TOKEN`은 필수는 아니다.
- 나중에 `Socket Mode`를 병행하거나 Slack Bolt 기반 worker를 붙일 때만 `SLACK_APP_TOKEN`이 필요하다.
- 승인 버튼을 쓰려면 Slack 앱의 `Interactivity & Shortcuts` 설정에서 인터랙션 URL도 등록해야 한다.
- `SLACK_AUTO_RESPONSE_CHANNELS` 에 채널 이름 또는 channel id를 넣으면, 해당 채널에서는 `@멘션` 없이도 일반 메시지에 반응한다. 현재 기본값은 `ai비서` 다.
- 현재 토큰에 channel 조회 scope가 없으면 이름 매칭은 실패할 수 있으므로, 실환경에서는 `SLACK_AUTO_RESPONSE_CHANNELS` 에 channel id를 넣는 구성이 가장 안전하다.

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
- `channels:history`
- `chat:write`
- `im:history`

선택 Scope:

- `chat:write.public`
설명: 앱이 초대되지 않은 공개 채널에도 쓰려는 경우만 추가한다.

- `channels:read`
설명: public channel 이름을 API로 확인해야 할 때 필요할 수 있다. 이 권한이 없으면 channel 이름 대신 channel id를 `SLACK_AUTO_RESPONSE_CHANNELS` 에 넣는 편이 더 확실하다.

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

중요:

- `ai비서` 채널처럼 멘션 없이 일반 메시지를 받으려면 `message.channels` Bot Event가 반드시 등록되어 있어야 한다.
- 이 이벤트가 없으면 서버 코드가 준비돼 있어도 Slack이 일반 채널 메시지를 보내지 않으므로, 결과적으로 `@멘션` 이 있을 때만 동작하는 것처럼 보이게 된다.

필수 Bot Events:

- `app_mention`
- `message.im`

특정 채널에서 멘션 없이도 받으려면 추가 Bot Event:

- `message.channels`

주의:

- 현재 공개 채널은 기본적으로 `app_mention` 이벤트를 처리한다.
- 다만 `SLACK_AUTO_RESPONSE_CHANNELS` 에 등록된 채널은 `message.channels` 이벤트를 통해 멘션 없이도 처리할 수 있다.
- DM은 `message.im` 이벤트를 사용한다.
- 서명 검증을 쓰므로 Slack이 보내는 실제 요청만 통과한다.

## Interactivity 설정

1. Slack 앱 설정의 `Interactivity & Shortcuts` 로 이동한다.
2. `Interactivity` 를 켠다.
3. Request URL 에 아래 경로를 넣는다.

```text
https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/interactions
```

이 설정이 있어야 승인 필요 응답에 포함된 `승인`, `거절` 버튼이 서버로 전달된다.

## Slack 앱 설정에서 추가로 확인할 항목

### App Home

- `Messages Tab` 을 켜 두면 DM 테스트가 쉬워진다.

### Event 대상 채널

- 일반 공개 채널 테스트는 앱을 채널에 초대한 뒤 `@앱이름 질문` 형식으로 보낸다.
- `ai비서` 채널처럼 `SLACK_AUTO_RESPONSE_CHANNELS` 에 등록된 채널은 멘션 없이 일반 메시지로 테스트할 수 있다.
- DM 테스트는 Slack 앱 홈 또는 직접 메시지 창에서 보낸다.

## 현재 동작 방식

### 공개 채널

- `@AI Assistant 최근 메일 요약해줘`
- `@AI Assistant 오늘 일정 요약해줘`
- `@AI Assistant 승인 <ticket_id>`

### 무멘션 허용 채널

- `ai비서` 채널은 기본 설정 기준 멘션 없이도 반응한다.
- `오늘 일정 요약해줘`
- `최근 메일 요약해줘`

### DM

- `최근 메일 요약해줘`
- `la9527@daum.net로 제목 테스트 내용 본문입니다 메일 초안 작성해줘`
- `승인 <ticket_id>`

현재 Slack 응답 방식:

- Slack Events API 요청에는 HTTP 레벨로 즉시 `accepted` 를 반환한다.
- 실제 사용자에게는 `chat.postMessage` 로 접수 메시지를 먼저 스레드에 보낸 뒤, 백그라운드 작업이 끝나면 최종 결과를 같은 스레드에 다시 보낸다.
- 승인 필요 작업이면 `approval_ticket_id` 를 생성하고, 최종 결과를 Block Kit 버튼 `승인`, `거절` 과 함께 보낸다.
- 버튼 클릭은 `POST /assistant/api/slack/interactions` 에서 즉시 ACK 한 뒤, 백그라운드에서 승인 또는 거절을 처리하고 결과를 다시 스레드에 보낸다.
- 토큰이 없거나 채널 접근 권한이 없으면 API는 처리하지만 Slack 메시지 전송은 `delivery=not_configured` 또는 Slack API 에러 상태로 남는다.

## 실환경 검증 절차

1. `.env` 에 `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` 를 넣는다.
2. API를 재빌드한다.
3. Slack 앱의 `Event Subscriptions` 에 `https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/events` 를 저장한다.
4. Slack 앱의 `Interactivity & Shortcuts` 에 `https://ai-assistant-kakao.la9527.cloud/assistant/api/slack/interactions` 를 저장한다.
5. 앱을 워크스페이스에 설치한다.
6. 앱을 테스트할 채널에 초대한다.
7. 아래 순서로 실제 메시지를 보낸다.

검증 순서:

1. 공개 채널에서 `@앱이름 최근 메일 요약해줘`
2. `ai비서` 채널에서 멘션 없이 `오늘 일정 요약해줘`
3. DM에서 `오늘 일정 요약해줘`
4. DM에서 `la9527@daum.net로 제목 슬랙 테스트 내용 본문입니다 메일 초안 작성해줘`
5. 응답에 표시된 `승인`, `거절` 버튼을 눌러 승인 흐름을 확인한다.
6. 필요하면 텍스트 명령 `승인 <ticket_id>` 도 함께 확인한다.

성공 기준:

- Slack 채널 또는 DM에서 먼저 접수 메시지가 빠르게 도착한다.
- 이후 같은 스레드에 최종 결과가 도착한다.
- 승인 필요 요청은 버튼 `승인`, `거절` 이 포함된 응답이 도착한다.
- 승인 버튼 클릭 후에는 같은 스레드에 실행 결과가 도착한다.

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
- 로그에 `channel_not_found` 가 보이면 앱이 채널에 초대되지 않았거나 테스트용 channel id가 실제 채널이 아닌 경우다.

### DM은 되는데 채널 mention이 안 됨

- `app_mention` Bot Event가 등록됐는지 확인한다.
- 채널에 앱이 초대됐는지 확인한다.

### 특정 채널에서 멘션 없이 반응하지 않음

- `SLACK_AUTO_RESPONSE_CHANNELS` 에 채널 이름 또는 channel id가 정확히 들어 있는지 확인한다.
- Slack 앱에 `message.channels` Bot Event가 등록됐는지 가장 먼저 확인한다. 이 항목이 빠져 있으면 채널 일반 메시지는 서버로 오지 않는다.
- API를 재빌드했는지 확인한다.
- 채널 이름 기준 매칭이 불안정하면 channel id를 `SLACK_AUTO_RESPONSE_CHANNELS` 에 넣는 편이 더 확실하다.
- Slack API에서 `missing_scope` 가 보이면 `channels:read` 권한을 추가하거나, channel id 기반으로 전환한다.

### `@멘션` 이 있어야만 동작하는 것처럼 보임

- Slack 앱의 Bot Events 에 `message.channels` 가 빠져 있지 않은지 확인한다.
- `ai비서` 채널의 channel id가 `SLACK_AUTO_RESPONSE_CHANNELS` 에 들어 있는지 확인한다.
- 앱이 해당 채널에 초대되어 있는지 확인한다.
- 위 세 가지가 맞는데도 안 되면 API 로그에서 `Received Slack event` 자체가 찍히는지 먼저 본다.

## 현재 남은 Slack 작업

- 실제 워크스페이스에서 채널 권한과 스레드 UX 검증
- 실제 승인 버튼 클릭 시 사용자 체감 UX와 중복 클릭 처리 확인
- 필요 시 채널별 응답 길이 제한과 후속 스레드 응답 정책 추가