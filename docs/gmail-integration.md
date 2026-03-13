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

`제목 AI Assistant Gmail 발송 테스트 내용 확인했습니다 메일에 답장해줘` 또는 `thread 18cc... 내용 후속 안내입니다 메일 이어서 보내줘` 요청을 보내면 아래 동작을 한다.

- 먼저 승인 티켓을 만든다.
- 제목이나 `thread id`, `message id`, `발신자` 정보를 바탕으로 최근 30일 메일에서 대상을 찾는다.
- 일반 답장은 `replyToSenderOnly=true` 로 회신하고, thread 이어쓰기는 기존 수신자 목록을 유지해 후속 메시지를 보낸다.

## 실제 연결 방법

1. `n8n` 편집기 `http://127.0.0.1:5678` 에 접속한다.
2. `Credentials` 메뉴에서 `Gmail OAuth2 API` credential을 생성한다.
3. Google Cloud Console에서 Gmail API를 활성화한다.
4. OAuth Client redirect URI를 `http://127.0.0.1:5678/rest/oauth2-credential/callback` 로 맞춘다.
5. Gmail credential 연결 후 `assistant-gmail-summary` workflow가 `gmailOAuth2` credential을 사용하는지 확인한다.

## 다음 권장 작업

- 현재 workflow는 최근 메일 5건 제목과 발신자 요약, 메일 초안 작성, 실제 발송, 메일 회신, thread 이어쓰기까지 구현되어 있다.
- 필요하면 다음 단계에서 첨부파일, 회신, 특정 thread 이어쓰기까지 확장할 수 있다.

## 현재 검증 기준

- `POST /assistant/api/chat` 에서 `최근 메일 요약해줘` 요청이 `route=n8n` 으로 처리되어야 한다.
- 응답은 최근 메일 목록 요약 또는 빈 메일함 안내 문구여야 한다.
- `POST /assistant/api/chat` 에서 메일 초안 또는 발송 요청은 먼저 `route=approval_required` 로 처리되어야 한다.
- 승인 후에는 초안 작성 또는 실제 발송 완료 문구가 반환되어야 한다.
- `POST /assistant/api/chat` 에서 메일 회신 또는 thread 이어쓰기 요청도 먼저 `route=approval_required` 로 처리되어야 한다.
- 승인 후에는 회신 실행 완료 문구가 반환되어야 한다.