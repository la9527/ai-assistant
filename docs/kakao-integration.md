# KakaoTalk 연동 가이드

## 현재 기준

- KakaoTalk 연동은 개인 계정 자동화가 아니라 Kakao 공식 채널과 OpenBuilder 또는 공식 webhook 방식만 사용한다.
- 외부 공개 경로는 Cloudflare Tunnel 뒤의 `https://ai-assistant-kakao.la9527.cloud/assistant/api/kakao/webhook` 이다.
- FastAPI는 `POST /assistant/api/kakao/webhook` 에서 Kakao 요청을 받아 공통 세션과 자동화 라우팅으로 넘긴다.
- 현재 공개 호스트 기준 `GET /assistant/api/health`, `POST /assistant/api/kakao/webhook` 실제 응답까지 검증됐다.

## 권장 연결 방식

가장 운영하기 쉬운 기준은 아래와 같다.

1. Kakao 공식 채널을 만든다.
2. Kakao i OpenBuilder에서 챗봇을 만든다.
3. OpenBuilder의 Skill 또는 webhook 연결 대상으로 FastAPI 공개 URL을 넣는다.
4. 운영자 접근은 Tailscale로만 하고, Kakao 사용자 요청만 Cloudflare Tunnel로 받는다.

이 구조를 쓰면 외부 공개 범위를 Kakao webhook 하나로 좁게 유지할 수 있다.

## 사전 준비

아래 항목이 먼저 준비되어 있어야 한다.

- Cloudflare Tunnel이 실행 중이어야 한다.
- `KAKAO_PUBLIC_BASE_URL` 이 실제 공개 호스트로 설정돼 있어야 한다.
- FastAPI와 proxy가 정상 기동 중이어야 한다.
- Kakao 관리자센터와 OpenBuilder를 수정할 수 있는 계정 권한이 있어야 한다.

현재 운영 기준 기동 명령:

```bash
docker compose -f infra/docker/docker-compose.yml up -d proxy postgres redis api worker webui n8n
docker compose --env-file .env -f infra/docker/docker-compose.yml --profile edge up -d cloudflared
```

## 서버 측 확인

Kakao 측 설정 전에 먼저 공개 URL이 살아 있는지 확인한다.

```bash
curl -i https://ai-assistant-kakao.la9527.cloud/assistant/api/health
```

Webhook 형식 응답 확인 예시:

아래 예시는 OpenBuilder 공식 SkillPayload 형식에 맞춘 테스트 요청이다.

```bash
curl -sS -X POST https://ai-assistant-kakao.la9527.cloud/assistant/api/kakao/webhook \
  -H 'Content-Type: application/json' \
  -d '{
    "bot": {
      "id": "test-bot-id",
      "name": "AI Assistant"
    },
    "action": {
      "id": "test-action-id",
      "name": "message",
      "params": {},
      "detailParams": {},
      "clientExtra": {}
    },
    "userRequest": {
      "block": {
        "id": "test-block-id",
        "name": "기본 블록"
      },
      "user": {
        "id": "kakao-test-user",
        "type": "botUserKey",
        "properties": {
          "plusfriendUserKey": "kakao-test-user"
        }
      },
      "utterance": "오늘 일정 요약해줘",
      "lang": "ko",
      "timezone": "Asia/Seoul",
      "params": {
        "surface": "BuilderBotTest"
      }
    }
  }'
```

정상이라면 `simpleText` 또는 `basicCard`, `quickReplies` 가 포함된 JSON 응답이 반환된다.

참고:

- 현재 서버는 OpenBuilder 실제 payload와 함께, 내부 수동 테스트용 간단 payload `{"user":{"id":"..."},"utterance":"..."}` 도 계속 허용한다.

## Kakao 공식 채널 준비

1. Kakao 공식 채널 관리자센터에서 비즈니스용 채널을 만든다.
2. 채널 프로필, 공개 상태, 기본 운영 정보를 설정한다.
3. 이후 OpenBuilder 챗봇과 연결할 채널을 이 채널로 선택한다.

주의:

- 개인 카카오 계정 자동화나 비공식 메시지 수집 방식은 이 저장소 기준에서 사용하지 않는다.
- 실제 사용자 테스트 전에는 운영자 계정만 채널에 연결해 점검하는 편이 안전하다.

## OpenBuilder 연결 절차

1. Kakao i OpenBuilder에서 새 챗봇을 만든다.
2. `채널 연결` 단계에서 앞서 만든 Kakao 공식 채널을 연결한다.
3. 기본 응답 블록 대신 webhook 또는 Skill 기반 응답으로 연결할 블록을 준비한다.
4. Skill 서버 URL 또는 webhook URL 입력란에 아래 주소를 넣는다.

```text
https://ai-assistant-kakao.la9527.cloud/assistant/api/kakao/webhook
```

5. 해당 Skill 또는 블록을 기본 진입 블록과 연결한다.
6. 저장 후 테스트 패널에서 메시지를 보내 응답을 확인한다.

실무 기준으로는 첫 진입 블록 하나만 FastAPI webhook으로 보내고, 세부 분기는 서버에서 처리하는 편이 단순하다.

## OpenBuilder에서 확인할 포인트

- 요청 메서드는 `POST` 여야 한다.
- 본문은 JSON 이어야 한다.
- 응답 대기 시간 제한 때문에 장기 작업은 즉시 접수 메시지 후 `callbackUrl` 기반 비동기 후속 응답 구조로 유지해야 안전하다.
- 긴 텍스트만 반복하기보다 `simpleText`, `basicCard`, `quickReplies` 조합을 유지하는 편이 Kakao UX에 맞다.

## 현재 서버 응답 방식

현재 FastAPI는 Kakao 요청을 받으면 아래 두 경로 중 하나로 응답한다.

- Kakao 공식 요청에 `callbackUrl` 이 포함된 경우:
  - 3초 이내에 `useCallback: true` 와 `data` 만 포함한 초기 ACK를 먼저 반환한다. 이 초기 응답에는 `template` 를 넣지 않는다.
  - 실제 자동화 실행은 백그라운드에서 진행한다.
  - 완료 후 같은 요청의 `callbackUrl` 로 최종 `simpleText` 또는 `basicCard` 를 다시 전송한다.
- 내부 수동 테스트나 `callbackUrl` 이 없는 요청인 경우:
  - 기존처럼 동기 응답을 바로 반환한다.

## 2026-03-15 작업 메모

- Kakao AI 챗봇 callback 가이드 기준으로 초기 ACK 응답은 `useCallback: true` 와 `data` 만 반환하도록 수정했다.
- `userRequest.callbackUrl` 와 top-level `callbackUrl` 를 모두 해석하도록 서버를 보강했다.
- callback 요청이 실제로 들어오면 초기 ACK 이후 백그라운드 작업을 수행하고, 완료 결과를 callback URL로 다시 POST하는 흐름까지 검증했다.
- 다만 실제 운영 채널 최근 호출 로그에서는 `has_callback=False` 로 들어온 요청이 반복 확인됐다. 즉 서버 수정과 별개로 운영 채널 일부 요청은 callbackUrl 없이 스킬 서버를 호출하고 있다.
- 운영 채널에서는 일부 요청이 서버까지 도달하지 않거나, 서버가 200으로 빠르게 응답했어도 Kakao 관리자센터에는 `스킬 서버 연결 오류 (1002)` 로 남는 사례가 있었다.
- 따라서 현재 Kakao는 구현 자체를 유지하되 운영 채널 우선순위는 낮추고, 다음 외부 채널 검증은 Slack 중심으로 진행한다.

- 일반 답변: `simpleText`
- 승인 필요 작업: `basicCard` 와 `quickReplies`
- 후속 제안: 일정 요약, 메일 요약, 메일 초안 작성 같은 quick reply

승인 필요 작업 예시:

- `la9527@daum.net로 제목 테스트 내용 본문입니다 메일 초안 작성해줘`
- 응답 안에 승인 안내와 ticket id가 포함된다.
- 이어서 Kakao 채널에서 `승인 <ticket_id>` 또는 `거절 <ticket_id>` 를 보내면 후속 실행이 진행된다.

## 실제 테스트 순서

1. OpenBuilder 테스트 패널에서 `오늘 일정 요약해줘` 를 보낸다.
2. Kakao 채널 채팅창에서 같은 요청을 보낸다.
3. 메일 초안 작성처럼 승인 필요한 요청을 보낸다.
4. 반환된 ticket id 기준으로 `승인 <ticket_id>` 를 보낸다.

권장 테스트 문장:

- `오늘 일정 요약해줘`
- `최근 메일 요약해줘`
- `la9527@daum.net로 제목 카카오 테스트 내용 본문입니다 메일 초안 작성해줘`
- `승인 <ticket_id>`

성공 기준:

- 채널에서 먼저 접수 메시지가 즉시 보인다.
- 느린 자동화는 잠시 후 최종 결과가 callback 응답으로 다시 도착한다.
- 승인 필요 요청은 카드 또는 quick reply가 포함된 최종 결과가 다시 전달된다.

현재 상태:

- 수동 callback payload 테스트는 성공했다.
 callbackUrl 이 없는 동기 webhook 경로에서는 승인 필요 응답과 `승인 <ticket_id>` 후속 요청까지 다시 검증했고, session history/state 저장과 `route=n8n` 완료 응답을 확인했다.
- 실제 운영 채널은 callback 미부여 호출과 `1002` 오류가 남아 있어 아직 성공 기준을 충족하지 못했다.

## 장애 점검 포인트

### Kakao에서 응답이 없을 때

- OpenBuilder 또는 관리자센터에 입력한 URL이 정확히 `https://ai-assistant-kakao.la9527.cloud/assistant/api/kakao/webhook` 인지 확인한다.
- Cloudflare Tunnel이 실행 중인지 확인한다.
- `GET /assistant/api/health` 가 공개 호스트 기준으로 응답하는지 확인한다.

### OpenBuilder 테스트는 되는데 실제 채널이 안 될 때

- 채널과 챗봇이 실제로 연결됐는지 확인한다.
- 기본 진입 블록이 webhook/Skill 블록으로 연결됐는지 확인한다.
- 채널 공개 상태와 관리자 권한을 확인한다.
- callback 사용 블록이라면 실제 운영 채널 요청 payload에 `userRequest.callbackUrl` 이 포함되는지 API 로그에서 먼저 확인한다.
- API 로그에 `has_callback=False` 가 반복되면 서버보다 OpenBuilder 블록 설정 또는 운영 채널 진입 경로를 먼저 의심한다.

### 응답은 오지만 자동화 결과가 이상할 때

- `N8N_*` webhook 경로와 token 설정을 확인한다.
- Gmail, Calendar 연동 문서 기준으로 n8n workflow가 살아 있는지 확인한다.
- 승인 흐름이면 PostgreSQL과 API 로그에서 ticket 생성 여부를 확인한다.

## 함께 보면 좋은 문서

- [docs/remote-access.md](docs/remote-access.md)
- [docs/gmail-integration.md](docs/gmail-integration.md)
- [docs/google-calendar-integration.md](docs/google-calendar-integration.md)
- [docs/architecture.md](docs/architecture.md)