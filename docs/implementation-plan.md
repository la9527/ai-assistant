# 구현 진행안

## 목표

현재 문서 설계를 실제 실행 가능한 최소 형태로 전환하고, 이후 기능을 순차적으로 붙일 수 있는 기반을 만든다.

## 1단계: 로컬 런타임 준비 ✅

- [x] `uv` 설치 및 Python 실행 환경 표준화
- [x] `Ollama` 설치 및 상시 실행 방식 검증
- [x] 필요 시 `LM Studio`는 사용자가 직접 설치 후 OpenAI 호환 API 포트 확인
- [x] 로컬 모델 1개 다운로드 및 응답 확인

## 2단계: 기본 애플리케이션 골격 ✅

- [x] `apps/api` FastAPI 서비스 추가
- [x] `apps/workers` 작업 실행 프로세스 추가
- [x] 공통 환경변수 파일 초안 추가
- [x] 헬스체크와 최소 API 엔드포인트 구현

## 3단계: Docker 운영 골격 ✅

- [x] `infra/docker/docker-compose.yml` 추가
- [x] `infra/caddy/Caddyfile` 추가
- [x] `PostgreSQL`, `Redis`, `n8n`, `Open WebUI`, `api`, `worker` 서비스 정의
- [x] 호스트의 `Ollama` 또는 `LM Studio` 연결 경로 정의

## 4단계: 최소 기능 MVP ✅

- [x] `POST /api/health`
- [x] `POST /api/chat`
- [x] `POST /api/slack/events`
- [x] PostgreSQL 기반 세션, 승인 티켓, 작업 상태 저장 구조
- [x] 로컬 LLM 라우팅용 설정 계층

## 현재 진행 상태

- `uv`, `Ollama`, `Docker Desktop` 설치 완료
- `qwen3:8b` 로컬 모델 다운로드 완료
- `FastAPI`, `worker`, `browser-runner` 초기 골격 추가 완료
- `docker-compose.yml`, `Caddyfile`, `.env.example` 추가 완료
- `Open WebUI` 실행 및 브라우저 접근 검증 완료
- 프록시 경로는 `Open WebUI=/`, `FastAPI=/assistant/api/*`로 분리했다.
- 카카오는 공식 채널과 OpenBuilder 또는 공식 webhook 방식만 사용한다.
- `POST /api/kakao/webhook` 스켈레톤 추가 및 프록시 경유 응답 검증 완료
- PostgreSQL에서 `kakao` 세션 적재까지 확인 완료
- `POST /api/chat`, `POST /api/kakao/webhook` 모두 로컬 LLM 실제 응답 경로 검증 완료
- `n8n` webhook 설정값과 자동화 라우팅 골격 추가 완료
- `n8n` 컨테이너 기동 및 API 컨테이너에서 `http://n8n:5678` 연결 검증 완료
- `workflows/n8n/assistant-automation.json` 기준의 샘플 webhook workflow 추가
- Kakao 응답은 `simpleText` 외에 `basicCard`와 `quickReplies`까지 확장 완료
- `n8n` workflow import 및 활성화 후 `route=n8n` 경로 검증 완료
- Google Calendar OAuth credential 연결 완료
- `assistant-automation` workflow를 실제 Google Calendar 조회 흐름으로 교체 완료
- `POST /assistant/api/chat`, `POST /assistant/api/kakao/webhook` 기준 실제 Calendar 조회 검증 완료
- 일정 생성과 변경은 승인 티켓 기반 실행 흐름까지 검증 완료
- 일정 삭제도 승인 티켓 기반 실행 흐름으로 확장 완료
- Gmail 경로는 `assistant-gmail-summary` workflow로 추가 완료
- Gmail OAuth credential 연결 완료
- `assistant-gmail-summary` workflow를 live 메일 요약 흐름으로 교체 완료
- Gmail 초안 작성과 메일 발송도 승인 기반 workflow로 확장 완료
- Gmail 회신과 `thread` 이어쓰기 승인 기반 workflow까지 검증 완료
- Gmail 첨부 URL 1건 다운로드 후 초안, 발송, 회신에 포함하는 흐름 검증 완료
- Gmail 회신 대상 선택은 제목, 발신자, 최근성 기준 scoring 로직으로 보강 완료
- Kakao 자동화 응답은 메일 첨부 초안, 첨부 회신 예시 quick reply와 카드 버튼까지 반영 완료
- Slack Events API 기준 `url_verification`, 서명 검증, DM 또는 app mention 메시지 처리, 승인 명령 처리, Bot token 기반 응답 전송 경로를 추가 완료
- Slack은 Events API 요청에 즉시 ACK를 반환하고, 실제 작업은 백그라운드에서 처리한 뒤 같은 스레드로 접수 메시지와 최종 결과를 다시 보내는 구조로 전환했다.
- Slack 승인 필요 응답은 Block Kit 버튼 기반 `승인`, `거절` 인터랙션으로 처리하도록 확장했다.
 로컬 ingress 기준 서명된 Slack DM 이벤트와 승인 버튼 인터랙션을 다시 검증했고, session messages/state에 승인 전후 상태와 최종 `route=n8n` 결과가 저장되는 것을 확인했다.
- Slack 실환경 검증은 공개 도메인과 HTTPS 준비 이후로 보류 상태다.
- `browser-runner`를 선택 프로필 서비스로 두고 `POST /assistant/api/browser/read` read-only 웹 추출 경로를 추가했다.
- 호스트용 `macos_runner`를 추가하고 승인 후 Notes 메모를 생성하는 AppleScript 시나리오를 연결했다.
- 외부 접근은 `Kakao=Cloudflare Tunnel`, `운영자 브라우저/n8n/SSH=Tailscale` 기준으로 정리하고, Compose에 선택 프로필 `cloudflared` 서비스를 추가했다.
- 브라우저 기반 macOS 원격 접근이 필요할 때를 위해 Compose에 선택 프로필 `remote-desktop` 과 `Guacamole + guacd` 구성을 추가하고, Caddy `/guacamole/*` 경로로만 노출하도록 정리했다.
- `cloudflared`는 `docker compose --env-file .env --profile edge up -d cloudflared` 기준으로 기동 검증했고, 공개 호스트에서 `GET /assistant/api/health`, `POST /assistant/api/kakao/webhook` 모두 실제 응답을 확인했다.
- Kakao callback 가이드에 맞춰 초기 ACK에서 `template` 를 제거하고 `useCallback: true` 와 `data` 만 반환하도록 조정했다.
- Kakao callback URL은 top-level과 `userRequest.callbackUrl` 양쪽 모두 지원하도록 보강했다.
 Kakao 동기 webhook 승인 follow-up 경로에서 발생하던 500 오류는 승인 명령 사용자 메시지 기록 시 structured payload를 필수로 요구하던 부분을 수정해 해결했다.
- 다만 실제 Kakao 운영 채널 로그에서는 `callbackUrl` 없이 들어오는 호출과 `1002` 오류가 남아 있어, 외부 채널 우선순위는 Slack 쪽으로 다시 이동했다.
- 웹 검색 통합: Tavily API 클라이언트(`app/search.py`), 검색 스킬 등록, `automation.py` 의도 분류와 라우팅, LangGraph `execute_web_search` 노드를 추가했다.
- 브라우저 러너 확장: `POST /browse/screenshot` (full-page PNG base64), `POST /browse/search` (Google 검색 결과) 엔드포인트를 추가하고 API에 프록시 경로를 연결했다.
- Worker 비동기 큐: `worker/main.py`를 Redis BRPOP 소비자로 재구현하고, API에 `POST /api/tasks/async` 발행과 `GET /api/tasks/async/{task_id}` 결과 조회 엔드포인트를 추가했다. 실제 Redis 큐 → Worker 처리 → 결과 저장 end-to-end 검증 완료.
- API 보안: `API_KEY` 환경변수가 설정되면 `X-API-Key` 헤더 기반 인증 미들웨어가 활성화된다. `/api/health`, `/api/kakao/*`, `/api/slack/*` 등은 인증 면제. `slowapi` 기반 rate limiting은 `/api/chat`에 분당 30회 기본값으로 적용된다.

## 현재 기준 남은 우선순위

- [ ] 1. `docs/implementation-plan.md`, `README.md`, `docs/architecture.md` 기준의 문서 상태를 계속 동기화한다.
- [x] 2. 공통 extraction schema를 기준으로 calendar, mail, note 요청을 순차적으로 LLM JSON extraction 기반으로 전환한다.
- [x] 3. session history와 state 저장 구조를 활용해 참조형 요청, 후보 선택형 삭제, 승인 후 재개 흐름을 보강한다. 순서 참조("두 번째", "1번") 파싱, 응답 후보 추출, 세션 상태 기반 후보 선택 적용, 도메인 계승 로직 구현 완료.
- [ ] 4. Slack 앱 설정에 `/assistant/api/slack/events`, `/assistant/api/slack/interactions` 를 반영하고 실제 워크스페이스에서 검증한다.
- [ ] 5. Slack 공개 채널, DM, 승인 버튼 흐름을 순서대로 실측하고 로그 기준 운영 점검 절차를 확정한다.
- [ ] 6. Kakao 운영 채널의 callbackUrl 누락 원인과 OpenBuilder 블록 설정 차이를 재검토한다.
- [ ] 7. Playwright 기반 브라우저 자동화 read-only 시나리오를 검증하고, 이후 승인 필요 시나리오로 확장할 정책과 결과 저장 형식을 정한다.
- [x] 8. AppleScript 기반 macOS 자동화는 Notes 외 Reminders, System Events(볼륨/다크모드), Finder로 확장 완료.
- [x] 9. FastAPI 중심 라우팅에서 LangGraph 기반 상태 라우팅과 승인 후 재개 구조로 점진 전환한다.
- [x] 10. 채널 간 사용자 매핑은 `user_identities` 기준으로 연결하고, 장기 메모리는 `user_memories` 기준으로 저장·관리한다. 관리자 경로는 `ADMIN_USERNAME`, `ADMIN_PASSWORD` 기반 로그인과 자동 발급 세션 cookie 기준으로 보호하고, 자동 메모리 적재는 명시적 선호/프로필 문장만 보수적으로 반영한다.
- [x] 11. 플러그인 및 스킬 확장 아키텍처를 기반으로 `automation.py`를 스킬 레지스트리와 도메인별 모듈로 분리한다. 상세 설계는 [docs/plugin-and-skill-architecture.md](plugin-and-skill-architecture.md)를 참조한다.
- [x] 12. 웹 검색 통합: Tavily API 기반 검색 + LLM 요약 파이프라인, 스킬 레지스트리 등록, LangGraph 노드 추가 완료.
- [x] 13. 브라우저 러너 확장: screenshot, Google 검색 엔드포인트 추가, API 프록시 및 브라우저 도메인 스킬 등록 완료.
- [x] 14. Worker 비동기 큐: Redis LIST 기반 LPUSH/BRPOP 작업 큐, API에서 `POST /api/tasks/async` 발행 및 `GET /api/tasks/async/{task_id}` 결과 조회, Worker 측 chat/web_search/callback 핸들러 구현 완료.
- [x] 15. API 인증 및 Rate Limiting: API_KEY 환경변수 기반 `X-API-Key` 헤더 미들웨어, slowapi 기반 `/api/chat` 분당 30회 제한, `/api/health`·`/api/kakao/*`·`/api/slack/*` 인증 면제 경로 설정 완료.
- [x] 16. MCP(Model Context Protocol) 클라이언트를 도입해 외부 도구 서버를 설정 파일(MCP_SERVERS 환경변수) 기반으로 연결한다. MCPManager, MCPConnection, 스킬 레지스트리 자동 등록, LangGraph execute_mcp_tool 노드 구현 완료.
- [x] 17. macOS 자동화를 MCP 서버로 격리해 Worker/API와 독립 배포 가능한 구조로 전환한다. apps/macos-mcp-server/ 에 stdio 모드 MCP 서버로 분리 완료.
- [x] 18. 외부 LLM 멀티 프로바이더 지원: OpenAI, Anthropic(Claude), Google Gemini 3사 API를 provider 설정으로 전환. 채팅과 구조화 추출 모두 외부 LLM 우선/fallback 모드 선택 가능. `_call_openai_compatible`, `_call_anthropic`, `_call_gemini` 디스패처 구현 완료.
- [x] 19. Open WebUI 연동: FastAPI에 OpenAI 호환 프록시 엔드포인트(`/v1/chat/completions`, `/v1/models`) 추가. Open WebUI가 FastAPI를 LLM 백엔드로 인식하여 일정·메일·노트 자동화를 웹 UI에서 직접 사용 가능. `ai-assistant` 모델 선택 시 자동화 파이프라인, 로컬 모델 선택 시 순수 채팅 포워딩. 스트리밍 지원.
- [ ] 14. 백업, 복구, 재기동 순서, 헬스체크, 로그 확인 절차를 운영 문서와 실제 검증 결과로 정리한다.

## 구조화 추출 전환 계획

- [x] 1. 공통 envelope 정의
  - [x] `domain`, `action`, `intent`, `confidence`, `needs_clarification`, `approval_required`, `missing_fields` 를 고정 필드로 둔다.
  - [x] calendar, mail, note payload는 envelope 하위 schema로 분리한다.

- [x] 2. session history와 state 저장
  - [x] 사용자 원문, assistant 응답, route, extraction 결과, 승인 메타데이터를 history에 저장한다.
  - [x] 마지막 intent, 최근 extraction, pending action, pending ticket, candidate 목록은 state에 저장한다.

- [x] 3. rule-based baseline 유지
  - [x] 현재 parser는 즉시 제거하지 않고 baseline extraction 생산용으로 유지한다.
  - [x] LLM extraction이 실패하거나 schema 검증을 통과하지 못하면 baseline 또는 clarification으로 내려간다.

- [x] 4. 도메인별 전환 순서
  - [x] 1차: `calendar_delete`, `gmail_reply`, `gmail_thread_reply`
  - [x] 2차: `calendar_create`, `calendar_update`, `gmail_draft`, `gmail_send`
  - [x] 3차: summary/list 계열 조회에 시간 범위 파싱(오늘/이번 주/내일 등) 추가, Gmail 검색 조건 자동 생성, 실행 노드에서 n8n으로 필터 전달 구현 완료

## 현재 1차 전환 상태

- `calendar_delete`, `gmail_reply`, `gmail_thread_reply` 는 recent history와 baseline extraction을 함께 local LLM에 보내 JSON extraction을 먼저 시도한다.
- 검증된 extraction JSON이 있으면 그 값을 우선 사용하고, 없으면 기존 parser로 안전하게 fallback 한다.
- message history와 session state를 활용한 후보 선택형 삭제와 참조형 후속 요청 해석이 구현 완료되었다. 응답에서 번호 목록을 추출(extract_candidates_from_reply)하고, 후속 "두 번째 삭제해줘" 같은 요청에서 순서 참조를 파싱(parse_ordinal_index)하여 해당 후보를 extraction payload에 자동 주입한다.
- 현재 기본 운영안은 일반 chat 과 structured extraction 모두 host MLX server의 `LFM2-24B-A2B-MLX-4bit` 단일 모델로 처리하는 구성이다.

## MLX 단일 모델 권장안

- 호스트 macOS에서 `mlx-lm` 으로 `lmstudio-community/LFM2-24B-A2B-MLX-4bit` 서버를 `1235` 에 기동한다.
- Open WebUI 는 `1236` filtered proxy 를 통해 같은 모델만 노출한다.
- FastAPI는 `LOCAL_LLM_BASE_URL` 과 `LOCAL_LLM_STRUCTURED_EXTRACTION_BASE_URL` 모두 같은 `1235` endpoint 를 사용한다.
- 이 방식은 32GB unified memory 환경에서 dual-model 상시 운영보다 memory pressure 와 swap 증가를 줄이기 쉽다.

## 현재 MLX structured extraction 검증 범위

- `calendar_create`, `calendar_update`, `calendar_delete`
- `gmail_draft`, `gmail_send`, `gmail_reply`, `gmail_thread_reply`
- 각 요청은 `assistant_messages` 에 `schema_mode=llm_structured_extraction` 와 `merged_with_baseline=true` 메타데이터로 저장되는지 확인한다.

## 승인 후 실제 실행 검증 결과

- `내일 오후 3시에 MLX 검증 치과 일정 추가해줘` 요청은 승인 후 `route=n8n` 으로 실제 일정 생성 완료 응답을 확인했다.
- `내일 오후 3시 MLX 검증 치과 일정 삭제해줘` 요청은 승인 후 `route=n8n` 으로 실제 일정 삭제 완료 응답을 확인했다.
- `test@example.com로 제목 MLX 검증 메일 내용 오늘 작업 완료 메일 초안 작성해줘` 요청은 승인 후 `route=n8n` 으로 실제 Draft 생성 완료 응답을 확인했다.

## MLX launchd 운영 확인 절차

- 재부팅 후 자동 시작 설치와 수동 운영 스크립트는 `infra/scripts/install-launchd-services.sh`, `infra/scripts/start-assistant-stack.sh`, `infra/scripts/stop-assistant-stack.sh`, `infra/scripts/status-assistant-services.sh` 기준으로 추가했다.
- stack 자동 시작 launchd label은 `com.aiassistant.stack` 이며, 자세한 절차는 `docs/service-operations.md` 에 정리한다.

1. 서비스 등록 상태 확인

- `launchctl list | grep com.aiassistant.mlx-base-server`
- `launchctl list | grep com.aiassistant.mlx-webui-proxy`

2. 모델 endpoint 확인

- `curl -sS http://127.0.0.1:1235/v1/models`
- `curl -sS http://127.0.0.1:1236/v1/models`

3. 로그 확인

- base server 표준 로그: `/tmp/aiassistant-mlx-base-server.log`
- base server 오류 로그: `/tmp/aiassistant-mlx-base-server.err.log`
- WebUI proxy 표준 로그: `/tmp/aiassistant-mlx-webui-proxy.log`
- WebUI proxy 오류 로그: `/tmp/aiassistant-mlx-webui-proxy.err.log`

4. 강제 재시작 검증

- base server 재시작 후 `curl -sS http://127.0.0.1:1235/v1/models` 와 `curl -sS http://127.0.0.1:1236/v1/models` 가 다시 성공하는지 확인한다.
- 현재 기본 운영안에서는 `1234` 구조화 추출 전용 서버를 비활성 상태로 둔다.

## Slack 실환경 적용 순서

1. Slack 앱 생성과 Scope 설정
2. `.env` 에 `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` 반영
3. `docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --build api` 로 API 재빌드
4. `Event Subscriptions` 에 `/assistant/api/slack/events` 등록
5. `Interactivity & Shortcuts` 에 `/assistant/api/slack/interactions` 등록
6. 워크스페이스 설치와 테스트 채널 초대
7. 공개 채널 발화, DM 발화, 승인 필요 요청, 버튼 승인 순서로 검증
8. `docker logs -f docker-api-1` 로 ACK와 후속 응답 로그 확인

## 5단계: 남은 기능 확장 순서

1. Slack 연동
2. 브라우저 자동화
3. macOS 자동화
4. LangGraph 상태 라우팅
5. 채널 통합 세션과 메모리 계층
6. 운영 복구 절차 검증

## 권한 또는 사용자 조치가 필요한 항목

- LM Studio 설치와 API 서버 활성화
- Cloudflare Tunnel 생성과 token 발급
- Tailscale 로그인과 tailnet 호스트 이름 확인
- Guacamole을 사용할 경우 macOS `Screen Sharing` 과 `VNC viewers may control screen with password` 설정
- Slack 앱 생성과 토큰 발급
- macOS 자동화 권한 부여

## 참고 문서

- Slack 실제 연결 절차는 `docs/slack-integration.md` 를 기준으로 진행한다.
- 외부 접근과 Kakao 공개 경로 적용 절차는 `docs/remote-access.md` 를 기준으로 진행한다.
- MLX 구조화 추출 서버 운영 절차는 `docs/mlx-operations.md` 를 기준으로 진행한다.
