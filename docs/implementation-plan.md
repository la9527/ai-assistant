# 구현 진행안

## 목표

현재 문서 설계를 실제 실행 가능한 최소 형태로 전환하고, 이후 기능을 순차적으로 붙일 수 있는 기반을 만든다.

## 1단계: 로컬 런타임 준비

- `uv` 설치 및 Python 실행 환경 표준화
- `Ollama` 설치 및 상시 실행 방식 검증
- 필요 시 `LM Studio`는 사용자가 직접 설치 후 OpenAI 호환 API 포트 확인
- 로컬 모델 1개 다운로드 및 응답 확인

## 2단계: 기본 애플리케이션 골격

- `apps/api` FastAPI 서비스 추가
- `apps/workers` 작업 실행 프로세스 추가
- 공통 환경변수 파일 초안 추가
- 헬스체크와 최소 API 엔드포인트 구현

## 3단계: Docker 운영 골격

- `infra/docker/docker-compose.yml` 추가
- `infra/caddy/Caddyfile` 추가
- `PostgreSQL`, `Redis`, `n8n`, `Open WebUI`, `api`, `worker` 서비스 정의
- 호스트의 `Ollama` 또는 `LM Studio` 연결 경로 정의

## 4단계: 최소 기능 MVP

- `POST /api/health`
- `POST /api/chat`
- `POST /api/slack/events`
- PostgreSQL 기반 세션, 승인 티켓, 작업 상태 저장 구조
- 로컬 LLM 라우팅용 설정 계층

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

## 5단계: 기능 확장 순서

1. Kakao webhook 스켈레톤
2. Gmail 또는 Calendar 자동화 1개
3. 승인 티켓 저장 구조 고도화
4. n8n 실행 연결
5. Slack 연동
6. 브라우저 자동화
7. macOS 자동화

## 권한 또는 사용자 조치가 필요한 항목

- Docker Desktop 설치와 최초 실행
- LM Studio 설치와 API 서버 활성화
- Slack 앱 생성과 토큰 발급
- Gmail, Calendar API 자격 증명 발급
- macOS 자동화 권한 부여
