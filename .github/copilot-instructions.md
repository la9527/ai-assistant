# AI Assistant Workspace Instructions

이 저장소에서 작업하는 에이전트는 아래 원칙을 기본값으로 따른다.

## 목적

- 맥미니 기반 self-hosted AI Assistant를 점진적으로 구현하고 운영 가능한 형태로 유지한다.
- 로컬 LLM, Open WebUI, FastAPI, n8n, PostgreSQL, Redis, Kakao 공식 채널을 중심으로 구조를 확장한다.
- 문서, 코드, 인프라 설정이 서로 어긋나지 않도록 유지한다.

## 현재 아키텍처 기준

- Open WebUI는 사용자 및 운영자용 웹 UI이며 외부 노출 경로는 `/` 이다.
- FastAPI는 코어 API이며 외부 노출 경로는 `/assistant/api/*` 이다.
- 로컬 LLM 기본 런타임은 Ollama이며 OpenAI 호환 경로는 `LOCAL_LLM_BASE_URL` 설정값을 따른다.
- n8n 기본 내부 주소는 `http://n8n:5678` 이다.
- 샘플 n8n workflow 파일은 `workflows/n8n/assistant-automation.json` 이다.
- 카카오는 개인 계정 자동화가 아니라 공식 채널, OpenBuilder, 공식 webhook 방식만 사용한다.

## 작업 원칙

- 문서 작성은 한글 우선을 유지한다. 기술 식별자, API 이름, 환경변수명은 영어 원문을 유지해도 된다.
- 사용자 요청이 구현을 요구하면 설명만 하지 말고 가능한 범위에서 실제 코드와 설정을 수정한다.
- 변경은 최소 범위로 유지하고, 기존 구조를 불필요하게 재편하지 않는다.
- FastAPI 경로, Docker Compose 설정, 문서는 함께 갱신한다.
- 카카오 응답은 일반 답변은 `simpleText`, 자동화 응답은 `basicCard` 또는 `quickReplies` 중심으로 유지한다.
- 일정, 메일, 노션 계열 요청은 n8n 경로를 우선 시도하고 실패 시 로컬 LLM fallback을 유지한다.
- 새 자동화 기능을 추가할 때는 `app/skills/` 아래에 도메인별 모듈로 분리하는 방향을 우선한다.
- 외부 도구 연결은 MCP 서버 설정을 우선 검토하고, 직접 구현은 MCP 인터페이스로 감쌀 수 없을 때만 허용한다.

## 구현 시 주의사항

- API 코드를 변경한 뒤에는 `docker compose -f infra/docker/docker-compose.yml up -d --build api` 로 재빌드해야 반영된다.
- PostgreSQL 기본 계정은 `app/app`, 데이터베이스명은 `assistant` 이다.
- Open WebUI와 FastAPI는 `/api` 경로를 공유하지 않는다.
- `.env` 는 로컬 실환경 설정 파일이므로 자동으로 삭제, 초기화, 재작성하지 않는다.
- 사용자가 명시적으로 요청하지 않는 한 파괴적인 Git 명령은 사용하지 않는다.

## 검증 기준

- API를 수정하면 최소한 `GET /assistant/api/health` 또는 관련 POST endpoint를 실제 호출해 본다.
- Kakao 관련 변경은 가능하면 `POST /assistant/api/kakao/webhook` 으로 검증한다.
- 자동화 관련 변경은 가능하면 API 경유 응답과 n8n 내부 webhook 연결을 함께 확인한다.
- Docker 관련 변경은 `docker compose -f infra/docker/docker-compose.yml logs <service> --tail 50` 수준의 로그 확인까지 포함한다.

## 우선순위 가이드

- 1순위: 현재 실행 중인 로컬 스택을 깨지 않는 변경
- 2순위: Kakao 주 채널과 FastAPI 게이트웨이 구조 유지
- 3순위: n8n 실행 경로와 로컬 LLM fallback 공존
- 4순위: 문서와 구현의 일치 유지

## 문서 동기화 대상

아래 파일은 구현 변경 시 같이 확인한다.

- `README.md`
- `docs/architecture.md`
- `docs/implementation-plan.md`
- `docs/plugin-and-skill-architecture.md`
- `infra/docker/docker-compose.yml`
- `infra/caddy/Caddyfile`

## Git 운영 기본값

- 작업 시작 전 `git status --short --branch` 로 상태를 확인한다.
- 사용자가 요청하면 작은 단위로 커밋한다.
- 커밋 메시지는 기능 단위로 명확하게 작성한다.

## 이 파일의 용도

- 이 파일은 이 저장소 전반에 항상 적용되는 workspace instruction 이다.
- 특정 파일군 전용 규칙이 더 필요해지면 `.github/instructions/*.instructions.md` 로 세분화한다.