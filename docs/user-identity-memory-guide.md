# 사용자 매핑 및 장기 메모리 운영 가이드

## 목적

이 문서는 최근 추가된 아래 기능을 운영자가 실제로 사용할 수 있도록 정리한다.

- 채널 외부 사용자 ID를 공통 내부 사용자 ID로 연결하는 `user_identities`
- 내부 사용자별 장기 메모리를 저장하는 `user_memories`
- 내장 관리자 페이지 `GET /assistant/api/admin/users`
- 명시적 사용자 지시를 기반으로 한 자동 장기 메모리 적재

현재 구현은 FastAPI 단일 서비스 안에서 동작하며, Slack, Kakao, Web 채널이 모두 같은 내부 사용자 ID를 공유할 수 있게 설계되어 있다.

## 현재 동작 요약

- Web, Slack, Kakao 입력에서 외부 사용자 ID가 들어오면 `user_identities` 를 통해 내부 사용자 ID로 정규화한다.
- 같은 내부 사용자 ID에 연결된 최근 세션을 재사용한다.
- 같은 내부 사용자 ID에 연결된 `user_memories` 일부를 로컬 LLM 응답 프롬프트에 참고 문맥으로 넣는다.
- 사용자가 `기억해줘`, `앞으로`, `다음부터`, `항상`, `참고해` 같은 명시적 표현을 쓰면 보수적인 규칙으로 자동 메모리 후보를 저장한다.
- 관리자 페이지와 identity, memory 관리 API는 `ADMIN_USERNAME`, `ADMIN_PASSWORD` 가 설정되어 있으면 로그인 세션 쿠키로 보호되고, 둘 다 비어 있으면 로그인 화면 없이 바로 열린다.

## 관련 엔드포인트

운영자가 직접 쓰게 되는 경로는 아래와 같다.

- 관리자 페이지: `GET /assistant/api/admin/users`
- identity 검색: `GET /assistant/api/users/identities`
- identity 단건 resolve: `POST /assistant/api/users/identities/resolve`
- identity 강제 link: `POST /assistant/api/users/identities/link`
- 내부 사용자의 identity 목록: `GET /assistant/api/users/{internal_user_id}/identities`
- 내부 사용자의 메모 목록: `GET /assistant/api/users/{internal_user_id}/memories`
- 내부 사용자 메모 생성: `POST /assistant/api/users/{internal_user_id}/memories`
- 내부 사용자 메모 수정: `PATCH /assistant/api/users/memories/{memory_id}`
- 내부 사용자 메모 삭제: `DELETE /assistant/api/users/memories/{memory_id}`

## 필요한 환경변수

### 필수는 아니지만 권장되는 값

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`

`ADMIN_USERNAME`, `ADMIN_PASSWORD` 를 모두 비워 두면 관리자 인증은 비활성화되고 바로 진입된다. 둘 다 설정하면 관리자 인증이 활성화된다. `ADMIN_SESSION_SECRET` 는 비어 있어도 동작하지만, 비어 있으면 API 재시작 때마다 세션 서명이 바뀌므로 운영에서는 명시적으로 두는 편이 안전하다.

예시:

```bash
ADMIN_USERNAME=operator
ADMIN_PASSWORD=change-this-password
ADMIN_SESSION_SECRET=change-this-long-random-secret
```

환경변수를 수정한 뒤에는 API를 다시 빌드한다.

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --build api
```

## 관리자 페이지 사용 방법

### 1. 토큰이 없는 경우

- `GET /assistant/api/admin/users` 로 바로 접속한다.
- identity 검색, link, 메모 생성/삭제를 바로 사용할 수 있다.

이 모드는 개인 운영이나 Tailscale 내부 전용 운영에는 단순해서 편하지만, 외부 노출 범위가 넓어지면 추천하지 않는다.

### 2. `ADMIN_USERNAME`, `ADMIN_PASSWORD` 가 설정된 경우

- `GET /assistant/api/admin/users` 로 들어가면 로그인 화면이 먼저 보인다.
- 관리자 ID와 비밀번호를 입력하면 FastAPI가 세션 토큰을 자동 발급하고 HttpOnly cookie로 저장한다.
- 이후 관리자 페이지의 후속 API 호출은 별도 토큰 입력 없이 같은 세션 cookie를 사용한다.

주의:

- 운영 환경에서는 `ADMIN_PASSWORD` 와 `ADMIN_SESSION_SECRET` 을 모두 충분히 긴 값으로 둔다.
- `ADMIN_SESSION_SECRET` 을 비워두면 서버 재시작 후 기존 관리자 로그인 세션은 모두 무효화된다.

## identity 운영 방식

### resolve 와 link 의 차이

`resolve`

- `(channel, external_user_id)` 조합이 처음이면 새 내부 사용자 ID를 만든다.
- 이미 있으면 기존 identity를 반환한다.
- 단순 등록 또는 조회에 가깝다.

`link`

- 특정 외부 사용자 ID를 이미 존재하는 내부 사용자 ID에 강제로 연결한다.
- 예를 들어 Slack 사용자와 Kakao 사용자가 실제로 같은 사람이라는 것이 확인되면 이 API로 합칠 수 있다.

### 운영 예시

1. Web에서 먼저 사용자가 들어와 내부 ID가 생성된다.
2. 운영자가 Slack 사용자 ID를 확인한다.
3. 관리자 페이지에서 같은 내부 사용자에 Slack ID를 `link` 한다.
4. 이후 Slack과 Web은 같은 장기 메모리와 최근 세션을 공유할 수 있다.

## 장기 메모리 운영 방식

### 수동 메모리

운영자가 직접 저장하는 메모다. 추천 용도는 아래와 같다.

- 선호 응답 형식
- 자주 반복되는 업무 스타일
- 사용자 프로필 중 비민감한 정보
- 특정 채널 운영 규칙

권장 예시:

- `일정 요약은 항상 짧고 핵심만 보여주기`
- `메일 초안은 존댓말로 시작하기`
- `이 사용자는 Slack과 Kakao를 같이 사용함`

저장하지 않는 편이 좋은 예시:

- 비밀번호
- OTP
- API key
- 개인 인증 정보
- 회전 주기가 짧은 비밀값

### 자동 메모리

현재 자동 적재는 의도적으로 보수적이다.

자동 적재 조건:

- 문장 길이가 너무 짧지 않을 것
- `기억해줘`, `기억해`, `앞으로`, `다음부터`, `항상`, `참고해` 같은 명시적 cue가 있을 것
- 비밀번호, 토큰, secret 계열 표현이 포함되지 않을 것

자동 분류 기준:

- 응답 스타일, 요약 방식, 말투 관련 표현은 `preference`
- 자기소개, 역할, 이름, 팀 정보 계열은 `profile`
- 그 외는 `general`

현재 자동 메모리 예시:

- `앞으로 일정 요약은 짧게 핵심만 보여줘, 기억해줘`
- `다음부터 답변은 존댓말로 해줘, 기억해줘`

현재 자동 메모리에서 제외되는 예시:

- `이 비밀번호는 1234야 기억해줘`
- `API key는 이거야 참고해`

## API 예시

### 1. identity resolve

```bash
curl -X POST http://127.0.0.1/assistant/api/users/identities/resolve \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "web",
    "externalUserId": "user-123",
    "displayName": "Operator Test"
  }'
```

### 2. identity link

```bash
curl -X POST http://127.0.0.1/assistant/api/users/identities/link \
  -H 'Content-Type: application/json' \
  -d '{
    "internalUserId": "<existing-internal-user-id>",
    "channel": "slack",
    "externalUserId": "U12345678",
    "displayName": "Slack User"
  }'
```

### 3. 메모 생성

```bash
curl -X POST http://127.0.0.1/assistant/api/users/<internal_user_id>/memories \
  -H 'Content-Type: application/json' \
  -d '{
    "category": "preference",
    "content": "일정 요약은 짧고 핵심만 보여주기",
    "source": "manual"
  }'
```

### 4. 메모 조회

```bash
curl -X GET 'http://127.0.0.1/assistant/api/users/<internal_user_id>/memories?limit=10' \
  --cookie 'ai_assistant_admin_session=<issued-session-cookie>'
```

## 운영 검증 절차

변경 후에는 아래 순서로 확인하는 편이 안전하다.

1. API 재빌드

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --build api
```

2. 헬스체크

```bash
curl -fsS http://127.0.0.1/assistant/api/health
```

3. 관리자 페이지 확인

- 토큰 미설정이면 `GET /assistant/api/admin/users`
- 로그인 설정이면 `GET /assistant/api/admin/users` 접속 후 브라우저에서 ID/PASS 로그인

4. identity resolve 또는 link 테스트

5. 메모 생성, 조회, 삭제 테스트

6. 실제 채팅 경로에서 자동 메모리 문장 1건 테스트

예시:

```bash
curl -X POST http://127.0.0.1/assistant/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "web",
    "userId": "memory-smoke-user",
    "message": "앞으로 일정 요약은 짧게 핵심만 보여줘, 기억해줘"
  }'
```

그 다음 `user_identities` 와 `user_memories` 조회 API로 실제 적재 여부를 확인한다.

## 현재 제한 사항

- 자동 메모리 적재는 아직 규칙 기반이며, 요약이나 추론을 넓게 하지 않는다.
- 관리자 페이지는 간단한 내장 HTML 페이지이므로 세부 편집 UX는 제한적이다.
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` 를 설정하지 않으면 관리자 경로가 내부망이라도 열려 있게 된다.
- 현재 Open WebUI 계정과는 로그인 세션을 공유하지 않는다.
- 장기 메모리는 참고 문맥으로만 사용되며, 절대적인 사실 저장소로 다루지 않는다.

## 다음 확장 후보

- 자동 메모리 후보를 검토 후 승인하는 운영 큐 추가
- profile, preference 외 메모리 카테고리 확장
- 관리자 페이지에서 메모리 수정 UI 추가
- 내부 사용자 병합 이력 감사 로그 추가