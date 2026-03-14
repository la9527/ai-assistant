# AI Assistant

맥미니를 로컬 추론 노드로 사용하고, 고난도 작업은 외부 LLM으로 라우팅하는 하이브리드 AI 개인 비서 프로젝트다.

이 프로젝트의 목표는 아래 세 가지 채널에서 동일한 비서 경험을 제공하는 것이다.

- 웹 UI
- Slack
- KakaoTalk

현재 외부 주 채널 우선순위는 KakaoTalk이며, 카카오 연동은 공식 채널과 OpenBuilder 또는 공식 webhook 경로만 사용한다.

현재 외부 접근 토폴로지는 아래 기준으로 고정한다.

- 외부 사용자와 Kakao webhook은 Cloudflare Tunnel을 통해 FastAPI 경로로만 들어온다.
- 본인 브라우저, 노트북, SSH 접근은 Tailscale tailnet 경로로만 사용한다.
- Open WebUI, n8n, SSH는 공개 인터넷에 직접 노출하지 않는다.

핵심 설계 원칙은 다음과 같다.

- 로컬 우선: 가능한 요청은 로컬 LLM에서 처리한다.
- 하이브리드 라우팅: 복잡한 작업만 외부 LLM으로 보낸다.
- 채널 분리: 웹, Slack, Kakao는 어댑터로 다루고 핵심 로직은 공통 계층에 둔다.
- 자동화 분리: 판단은 LangGraph, 외부 API 실행은 n8n으로 분리한다.
- 승인 기반 실행: 시스템 조작, 메시지 발송, 브라우저 자동화는 승인 단계를 둔다.

## 상위 수준 기술 스택

- 로컬 LLM 런타임: Ollama 또는 LM Studio
- 웹 UI: Open WebUI
- 코어 API: FastAPI
- 에이전트 오케스트레이션: LangGraph
- 자동화: n8n
- 메시징: Slack Events API, Kakao 채널 webhook/OpenBuilder
- 데이터: PostgreSQL, Redis
- 로컬 자동화: AppleScript, Playwright, Open Interpreter

## 단계별 구현 계획

### 0단계

기본 운영 기반을 먼저 준비한다.

- Reverse proxy
- HTTPS
- Redis
- PostgreSQL
- 환경변수 및 시크릿 관리
- 백업 및 복구 기준 수립
- 장애 감지와 재기동 절차 정의

### 1단계

로컬 추론 환경을 안정화한다.

- Ollama 또는 LM Studio 설치
- Open WebUI 및 코어 API 연결
- 로컬 모델 1~2개 선정 및 검증
- 런타임별 성능 비교와 운영 기준 수립
- 응답 속도, 메모리 사용량, 품질 기준 수립

### 2단계

공통 백엔드와 최소 에이전트 라우팅을 만든다.

- FastAPI 기반 공통 API
- LangGraph 최소 라우터
- Slack Events API 연동

### 3단계

외부 서비스 자동화를 추가한다.

- n8n 연결
- Gmail
- Google Calendar
- Notion
- 장기 실행 작업과 스케줄 작업 분리

### 4단계

Kakao 채널을 추가한다.

- Kakao 공식 채널 webhook 또는 OpenBuilder 연동
- 채널별 메시지 포맷 표준화
- 공개 HTTPS 엔드포인트 검증
- FastAPI를 카카오 이벤트 수신 게이트웨이로 사용
- n8n은 카카오 응답 이후 실행되는 자동화 계층으로만 사용

### 5단계

맥 자동화를 추가한다.

- AppleScript 기반 네이티브 작업
- Playwright 기반 브라우저 자동화
- Open Interpreter 기반 고급 실험 기능
- 승인 흐름 및 감사 로그 추가

## 권장 저장소 구조 방향

현재는 문서 중심으로 시작하고, 구현이 진행되면 아래와 같은 구조를 권장한다.

```text
.
├── README.md
├── docs/
│   └── architecture.md
├── apps/
│   ├── api/
│   ├── workers/
│   └── web/
├── packages/
│   ├── agent-core/
│   ├── channel-adapters/
│   ├── automation-clients/
│   └── shared/
├── infra/
│   ├── docker/
│   ├── caddy/
│   └── scripts/
└── workflows/
    └── n8n/
```

## 핵심 설계 문서

- [docs/architecture.md](docs/architecture.md)
- [docs/remote-access.md](docs/remote-access.md)
- [docs/google-calendar-integration.md](docs/google-calendar-integration.md)
- [docs/gmail-integration.md](docs/gmail-integration.md)
- [docs/slack-integration.md](docs/slack-integration.md)

## 현재 검증된 자동화 범위

- Google Calendar 오늘 일정 요약
- Google Calendar 일정 생성, 변경, 삭제 승인 실행
- Gmail 최근 메일 요약
- Gmail 메일 초안 작성과 실제 발송 승인 실행
- Gmail 회신과 thread 이어쓰기 승인 실행
- Gmail 첨부 URL 1건 포함 초안 작성, 실제 발송, 회신 실행
- Kakao 자동화 카드와 quick reply 기준의 메일 첨부 예시 UX 검증
- Slack Events API 기준 `url_verification`, app mention, DM, 승인 필요 응답 경로 로컬 payload 검증

## 현재 보류 사항

- Slack 실제 워크스페이스 검증은 공개 도메인과 HTTPS 경로가 준비된 뒤 진행한다.

## 현재 접근 경로

- Kakao 공개 webhook URL은 Cloudflare Tunnel 뒤의 `https://<kakao-host>/assistant/api/kakao/webhook` 형태를 사용한다.
- Open WebUI 운영 접근은 Tailscale 호스트명 기준 `http://<tailscale-host>/`를 사용한다.
- n8n 운영 접근은 Tailscale 호스트명 기준 `http://<tailscale-host>:5678`를 사용한다.
- SSH는 Tailscale 네트워크 위의 일반 SSH만 사용하고, macOS `Remote Login`을 켠 뒤 `ssh <mac-user>@<tailscale-host>` 형식으로 접속한다.

## 현재 남은 우선순위

1. 공개 도메인 준비 후 Slack 실제 워크스페이스 연동과 토큰 기반 이벤트 검증
2. Playwright 기반 브라우저 자동화 read-only 경로를 실사용 기준으로 다듬고 승인 필요 시나리오로 확장
3. AppleScript 기반 macOS 자동화 승인 시나리오를 실사용 기준으로 다듬고 추가 앱으로 확장
4. LangGraph 상태 라우팅과 승인 후 재개 구조 도입
5. 채널 통합 사용자 매핑과 장기 메모리 계층 추가
6. 백업, 복구, 재기동 절차의 실제 검증과 문서화

브라우저 자동화는 선택 프로필 서비스 `browser-runner`를 통해 분리한다. 현재는 `POST /assistant/api/browser/read`로 대상 URL의 제목, 설명, 주요 heading, 본문 일부를 read-only 방식으로 추출할 수 있다.

macOS 자동화는 컨테이너가 아니라 호스트 프로세스로 분리한다. 현재는 `uv run --project apps/workers python -m worker.macos_runner`로 host runner를 띄운 뒤, 승인 기반으로 Notes 메모를 생성하는 흐름을 사용할 수 있다.

Cloudflare Tunnel 적용은 `docker compose --env-file .env --profile edge up -d cloudflared` 기준으로 운영하고, Tailscale 적용 절차와 호스트 접근 규칙은 [docs/remote-access.md](docs/remote-access.md)에 정리한다.

현재 확인된 Tailscale 호스트명은 `byoungyoung-macmini.tail53bcc7.ts.net` 이며, Open WebUI와 n8n은 이 호스트명으로 200 응답까지 확인했다. 다만 SSH는 `tailscale up --ssh` 대신 macOS 기본 `Remote Login`을 이용하는 방식으로 운영한다.

## OpenClaw 반영 확장 방향

현재 구조에 OpenClaw 계열 기능을 반영하면, 시스템은 단순 채팅 인터페이스가 아니라 채널 통합형 실행 에이전트로 확장된다.

핵심 변화는 아래와 같다.

- 채널별 대화가 공통 세션과 사용자 컨텍스트로 연결된다.
- 단순 답변 외에 도구 실행, 외부 SaaS 자동화, 브라우저 조작, 로컬 시스템 작업까지 처리한다.
- 위험 작업은 승인 후 재개 가능한 상태 머신으로 관리한다.
- 장기 메모리와 작업 이력을 사용해 반복 업무를 점점 짧은 지시로 처리할 수 있게 된다.
- 재사용 가능한 스킬 단위로 업무 능력을 추가할 수 있다.

## 기능 확장 단계

### MVP

가장 먼저 반드시 들어가야 하는 기능이다.

- 채널 공통 세션 ID와 사용자 매핑
- FastAPI 단일 진입점과 LangGraph 최소 상태 라우팅
- 로컬 LLM 우선, 외부 LLM 예외 라우팅
- Ollama 또는 LM Studio 중 하나를 선택 가능한 로컬 추론 구조
- 승인 티켓 생성, 승인 후 재개, 감사 로그
- Slack 기준 액션형 자동화 1~2개
- Gmail 또는 Calendar 중 1개 워크플로 연동
- 기본 장기 메모리 저장 구조

### 확장 단계

OpenClaw와 비슷한 운영감을 만들기 위해 다음 단계에서 추가한다.

- Kakao 채널 합류 및 채널 간 동일 사용자 식별
- Playwright 기반 브라우저 작업을 1급 도구로 승격
- AppleScript 기반 macOS 앱 제어
- 작업 유형별 리스크 정책과 승인 정책 세분화
- 프로젝트 또는 사용자 단위 스킬 레지스트리
- 백그라운드 장기 작업, 예약 실행, 재시도 큐
- 대화 요약, 메모리 압축, 세션 리셋 정책

### 고급 단계

장기적으로 운영 복잡도를 올리는 대신 제품 완성도를 높이는 단계다.

- 멀티채널 알림 fan-out
- 브라우저 프로필 분리와 원격 브라우저 연결
- Open Interpreter 계열 고급 시스템 실행 실험
- 자주 쓰는 작업에 대한 반자동 proactive 제안
- 스킬 배포, 버전 관리, 사용자별 허용 범위
- 세션 포크, 작업 위임, 서브에이전트 실행

## 초기 구현 우선순위

1. Ollama 또는 LM Studio와 Open WebUI를 먼저 안정화한다.
2. FastAPI와 LangGraph로 공통 실행 경로를 만든다.
3. Slack을 첫 번째 외부 채널로 붙인다.
4. n8n으로 Gmail, Calendar, Notion 자동화를 연결한다.
5. Kakao와 Mac 자동화를 순차적으로 확장한다.

## 카카오 채널 운영 원칙

- 카카오는 개인 계정 자동화가 아니라 공식 비즈니스 채널만 사용한다.
- 카카오 입력은 FastAPI가 수신하고, 내부 공통 세션 포맷으로 정규화한다.
- 실제 업무 실행은 LangGraph 판단 이후 n8n 또는 내부 실행기로 넘긴다.
- Open WebUI는 운영자 확인과 디버깅용 UI로 사용하고, 외부 사용자 주 채널은 카카오에 둔다.

## 운영 및 복구 기본 원칙

실제 운영 환경을 만든 이후에는 기능 구현만큼 복구 전략이 중요하다. 현재 구조는 단일 맥미니 기반 self-hosted 구성이므로, 장애가 나면 전체 서비스가 동시에 영향을 받는다.

우선 반영해야 할 기준은 아래와 같다.

- PostgreSQL, n8n workflow, 환경변수, 프롬프트, 스킬 정의는 정기 백업한다.
- LangGraph 작업 상태와 승인 티켓은 재시작 후 이어받을 수 있게 저장형 상태로 관리한다.
- 로그, 스크린샷, 브라우저 산출물은 서비스 데이터와 분리 저장한다.
- 서비스별 재기동 순서를 문서화한다.
- 맥 재부팅 후 자동 시작 여부를 사전에 검증한다.
- 운영 중 장애 유형별 점검 절차와 롤백 절차를 준비한다.

## Docker 기반 운영 방향

현재 구조에는 Docker를 기본 운영 방식으로 채택하는 편이 적절하다. 다만 모든 요소를 컨테이너에 넣기보다 `Docker 중심 + macOS 호스트 실행`의 혼합 구성이 가장 현실적이다.

Docker에 올리기 좋은 구성요소:

- Caddy 또는 Nginx
- Open WebUI
- FastAPI
- LangGraph worker
- n8n
- PostgreSQL
- Redis
- 선택적 Playwright runner

macOS 호스트에 두는 것이 더 적절한 구성요소:

- Ollama 또는 LM Studio
- AppleScript 기반 자동화 실행기
- macOS 앱 제어 워커
- Open Interpreter 실험 계층

권장 이유는 아래와 같다.

- 애플리케이션 계층은 Docker Compose로 재현성과 복구성을 확보할 수 있다.
- macOS 고유 기능은 호스트 권한을 직접 써야 안정적이다.
- 로컬 LLM 런타임과 컨테이너 계층을 분리하면 장애 원인 파악이 쉬워진다.
- 데이터 계층은 볼륨으로 분리해 백업과 복원을 단순화할 수 있다.