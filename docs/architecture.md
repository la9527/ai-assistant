# 아키텍처 초안

## 목표

이 시스템은 다음 요구를 만족하는 AI 개인 비서를 목표로 한다.

- 맥미니에서 로컬 LLM을 안정적으로 운영할 수 있어야 한다.
- 고난도 추론, 장문 분석, 비용 대비 품질이 중요한 작업은 외부 LLM을 사용할 수 있어야 한다.
- 웹 UI, Slack, KakaoTalk에서 동일한 비즈니스 로직을 재사용해야 한다.
- Gmail, Calendar, Notion 등 외부 SaaS 자동화가 가능해야 한다.
- 향후 맥 로컬 자동화까지 확장할 수 있어야 한다.

## 비목표

초기 단계에서 아래 항목은 우선순위가 아니다.

- 대규모 멀티테넌트 SaaS
- 고가용성 멀티리전 배포
- 완전 자율 실행 에이전트
- 복잡한 프론트엔드 커스텀 UI

## 시스템 개요

```mermaid
flowchart TB
  User[User]
  Kakao[KakaoTalk\nOfficial Channel and OpenBuilder]
  Browser[Owner Browser / Laptop]
  Cloudflare[Cloudflare Tunnel]
  Tailscale[Tailscale Tailnet]

  Proxy[Reverse Proxy\nCaddy]
    API[FastAPI Core API]
    Graph[LangGraph Router\nState and Approval Flow]
    N8N[n8n Automation]
  Web[Web UI\nOpen WebUI]
    LocalRuntime[Local LLM Runtime\nOllama or LM Studio or MLX]
    ExtLLM[External LLM Providers]
    Redis[Redis]
    Postgres[PostgreSQL]
    MacTools[AppleScript / Playwright / Open Interpreter]

  Kakao --> Cloudflare
  Cloudflare --> Proxy
  Browser --> Tailscale
  Tailscale --> Proxy
  Tailscale --> N8N
  Tailscale --> MacTools

    Proxy --> API
  Proxy --> Web
  Web --> API

    API --> Graph
    Graph --> LocalRuntime
    Graph --> ExtLLM
    Graph --> N8N
    Graph --> MacTools

    API --> Redis
    API --> Postgres
    N8N --> Postgres
    N8N --> Redis
```

> **Open WebUI ↔ FastAPI 연동**: Open WebUI는 `OPENAI_API_BASE_URLS=http://api:8000/v1`로 설정되어 FastAPI의 OpenAI 호환 엔드포인트(`/v1/chat/completions`, `/v1/models`)를 통해 자동화 파이프라인에 직접 접근한다. 모델 드롭다운에서 `ai-assistant`를 선택하면 일정·메일·노트 등 개인 비서 기능이 동작하고, 로컬 MLX 모델을 선택하면 순수 채팅으로 포워딩된다.

  ## 현재 외부 접근 토폴로지

  현재는 외부 노출을 아래처럼 분리한다.

  - 공개 ingress: Kakao 공식 채널 webhook만 Cloudflare Tunnel을 통해 수신한다.
  - 운영자 접근: Open WebUI, n8n, SSH, 선택적 Guacamole 브라우저 원격 데스크톱은 Tailscale tailnet 경로로만 접근한다.
  - 맥미니 내부 서비스: FastAPI, n8n, Open WebUI, Ollama, Redis, PostgreSQL이 내부 실행 계층을 구성한다.

  이 결정의 목적은 카카오 공개 webhook 경로만 좁게 노출하고, 운영자용 UI와 SSH는 공개 인터넷에서 분리하는 것이다.

## 설계 원칙

### 1. 채널 어댑터는 얇게 유지한다

웹, Slack, Kakao는 입력과 출력 포맷만 다루고, 판단 로직은 공통 계층에 둔다.

### 2. 판단과 실행을 분리한다

- LangGraph: 상태 기반 라우팅, 승인 흐름, 분기 판단
- n8n: 외부 서비스 실행, 스케줄링, 웹훅 기반 자동화

### 2-1. 자유 답변 전에 구조화 추출을 먼저 만든다

- 사용자 발화는 먼저 공통 extraction JSON으로 정규화한다.
- extraction JSON은 `domain`, `action`, `intent`, `confidence`, `needs_clarification`, `approval_required`, `missing_fields` 와 도메인별 payload를 포함한다.
- calendar, mail, note 같은 도메인별 payload는 공통 envelope 아래에 분리한다.
- 자동화 실행은 자유 텍스트가 아니라 검증된 extraction JSON을 기준으로 수행한다.
- 현재는 rule-based baseline extraction을 먼저 저장하고, 이후 동일 schema에 LLM JSON extraction을 연결한다.

### 2-2. 메일 읽기 기능은 단일 요약이 아니라 읽기 도구 집합으로 확장한다

- 메일 읽기 기능은 `gmail_summary` 하나로 오래 유지하지 않는다.
- 목표 구조는 `gmail_list`, `gmail_detail`, `gmail_thread` 로 분리된 읽기 도구 집합이다.
- LLM은 사용자의 의도를 해석해 적절한 읽기 도구와 파라미터를 선택한다.
- FastAPI/LangGraph는 구조화 추출, 세션 상태, 후보 선택, 후속 참조 해석을 담당한다.
- n8n은 실제 Gmail API 호출과 결과 정규화를 담당한다.
- 이 구조를 통해 날짜별 그룹화, 더보기, 다건 선택, 상세 조회, 스레드 조회를 공통 모델 위에서 확장할 수 있다.

### 3. 로컬 우선, 필요할 때만 외부 모델 사용

기본 응답은 로컬 모델을 사용하고, 아래 조건에서만 외부 모델로 보낸다.

- 긴 문맥 처리 필요
- 높은 정확도 요구
- 복잡한 도구 선택 및 장기 계획 필요
- 로컬 모델 품질 한계 도달

### 4. 위험 작업은 사람 승인 우선

아래 작업은 승인 단계를 기본값으로 둔다.

- 이메일 발송
- 일정 생성 또는 수정
- 노션 페이지 생성 또는 삭제
- 파일 삭제 또는 이동
- 브라우저 자동화 실행
- 맥 시스템 명령 실행

### 5. 채널 간 세션 연속성 보장

웹, Slack, Kakao 중 어느 채널에서 들어와도 동일 사용자라면 같은 작업 이력, 메모리, 승인 상태를 이어받을 수 있어야 한다.

이를 위해 세션 계층은 아래 두 저장소를 기본으로 둔다.

- message history: 사용자 원문, assistant 응답, route, 구조화 extraction 결과, 승인 관련 메타데이터 저장
- session state: 마지막 intent, 마지막 route, pending action, pending ticket, 최근 extraction, 후보 목록, 보조 상태 저장

### 5-1. 대용량 데이터는 외부 SSD로 분리한다

- 모델 캐시, Docker 영속 데이터, 운영 중 커지는 상태 파일은 가능하면 시스템 디스크가 아니라 외부 SSD로 분리한다.
- 현재 기본 저장 루트는 `/Volumes/ExtData/ai-assistant` 이다.
- Docker Compose 서비스 데이터는 bind mount 로 이 경로 아래에 두고, MLX/Hugging Face 캐시는 `/Volumes/ExtData/ai-assistant/mlx` 기준으로 맞춘다.
- 이 구조의 목적은 macOS 시스템 디스크 압박을 줄이고, 모델/워크플로/DB 데이터를 한 경로에서 백업 가능하게 만드는 것이다.

### 6. 하드코딩보다 스킬 중심 확장

반복 가능한 업무 능력은 개별 기능으로 고정 구현하기보다 스킬 단위로 등록 가능한 구조를 우선한다. 외부 도구 서버는 MCP(Model Context Protocol) 표준 인터페이스로 연결해 내부 스킬과 같은 방식으로 호출한다.

### 7. 브라우저와 로컬 실행을 1급 도구로 취급

브라우저와 macOS 로컬 실행은 부가 기능이 아니라 핵심 실행 도구로 취급해야 한다. 다만 권한, 승인, 감사 로그 정책을 항상 함께 둔다.

## 주요 구성요소

## 1. Open WebUI

역할:

- 웹 기반 사용자 인터페이스
- 로컬 및 외부 모델을 통합해 보여주는 운영 UI
- 초기 운영과 디버깅에 적합한 관리형 채팅 인터페이스

채택 이유:

- Ollama와 연결이 단순하다.
- LM Studio를 포함한 OpenAI 호환 로컬 API와 함께 연결할 수 있다.
- OpenAI 호환 API도 함께 연결 가능하다.
- 모바일 대응과 빠른 운영 테스트에 유리하다.

제한:

- 핵심 비즈니스 로직을 여기에 넣지 않는다.
- Slack/Kakao와 동일한 행동을 보장하는 계층은 아니다.

## 2. FastAPI 코어 API

역할:

- 단일 진입점
- 인증, 권한, 사용자 컨텍스트 로딩
- 채널별 payload 정규화
- LangGraph 호출
- 응답 포맷 변환

주요 엔드포인트 초안:

- `POST /api/chat`
- `POST /api/slack/events`
- `POST /api/kakao/webhook`
- `POST /api/actions/approve`
- `POST /api/actions/reject`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/messages`
- `GET /api/sessions/{session_id}/state`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/async` — Redis 큐로 비동기 작업 발행
- `GET /api/tasks/async/{task_id}` — 비동기 작업 결과 조회
- `POST /api/browser/read` — 웹 페이지 본문 읽기 프록시
- `POST /api/browser/screenshot` — 웹 페이지 스크린샷 프록시
- `POST /api/browser/search` — 브라우저 기반 Google 검색 프록시
- `GET /api/health`

현재 FastAPI의 Slack 경로는 아래 범위를 포함한다.

- `url_verification` challenge 응답
- Slack signing secret 기반 서명 검증
- DM 또는 `app_mention` 메시지 처리
- 승인 명령 `승인 <ticket_id>`, `거절 <ticket_id>` 처리
- Bot token이 있으면 `chat.postMessage` 기준 응답 전송

## 3. LangGraph 라우터

역할:

- 대화 상태 관리
- 요청 분류
- 로컬 LLM과 외부 LLM 라우팅
- 도구 호출 전 승인 필요 여부 판단
- 실패 복구와 긴 작업 상태 저장

초기 그래프 초안:

```text
ingest
  -> extract_structured_request
  -> classify_request
  -> load_context
  -> decide_route
      -> local_llm_path
      -> external_llm_path
      -> automation_path
      -> approval_path
  -> finalize_response
```

LangGraph에 적합한 영역:

- 상태 기반 멀티스텝 대화
- 승인 대기 후 재개
- 장기 실행 작업 추적
- 사용자 메모리 적용
- 승인 후 상태 재개
- 브라우저 및 시스템 도구 호출 전 정책 판정
- extraction JSON 검증 실패 시 clarification 분기
- history와 last_candidates를 활용한 참조 해석
- 스킬 레지스트리 기반 의도 분류와 도구 선택
- MCP 도구 서버 호출을 내부 스킬과 동일한 실행 노드에서 처리

LangGraph에 과도한 영역:

- 단순 SaaS CRUD 연동
- 정기 스케줄 작업
- webhook fan-out

## 4. n8n 자동화 계층

역할:

- Gmail, Calendar, Notion 같은 외부 서비스 연결
- 정기 작업, 트리거 기반 작업, 후처리
- 외부 앱별 인증 관리

권장 원칙:

- n8n은 실행 계층으로 사용한다.
- LangGraph가 직접 각 SaaS API를 다루지 않도록 한다.
- FastAPI 또는 LangGraph가 n8n workflow를 호출하는 형태로 연결한다.

초기 워크플로 후보:

- 메일 요약 후 드래프트 생성
- 캘린더 일정 등록 전 중복 확인
- 노션 DB에 회의 요약 저장
- 매일 아침 일정 브리핑 생성

현재 샘플 workflow 기준:

- `workflows/n8n/assistant-automation.json`
- webhook 경로는 `/webhook/assistant-automation`

메일 읽기 확장 시에는 아래 workflow 구성을 권장한다.

- `assistant-gmail-list`
- `assistant-gmail-detail`
- `assistant-gmail-thread`

기존 `assistant-gmail-summary` 는 초기 하위 호환 경로로 유지하되, 내부적으로는 목록 조회 workflow 성격으로 점진 전환한다.
- 현재는 `assistant-automation`, `assistant-calendar-create`, `assistant-calendar-update`, `assistant-calendar-delete`, `assistant-gmail-summary`, `assistant-gmail-draft`, `assistant-gmail-send`, `assistant-gmail-reply` workflow로 분리되어 있다.
- 캘린더 쓰기와 메일 초안, 발송, 회신은 모두 승인 티켓 이후에만 실행한다.
- Gmail 자동화는 최근 메일 요약, 초안 작성, 실제 발송, 제목 또는 발신자 기반 회신 대상 선택, `thread` 이어쓰기까지 검증되어 있다.
- `첨부 https://...` 형식의 공용 URL 1건은 초안, 발송, 회신 workflow에서 실제 첨부파일로 내려받아 포함할 수 있다.

## 5. 로컬 LLM 런타임과 모델 계층

역할:

- 기본 대화 처리
- 개인정보가 포함된 로컬 우선 작업
- 빠른 초안 생성

권장 구조:

- 로컬 추론 런타임은 `Ollama`, `LM Studio`, `MLX` 중 용도에 맞게 선택 가능하게 둔다.
- FastAPI 또는 공통 LLM 클라이언트 계층에서 런타임 차이를 흡수한다.
- 가능하면 OpenAI 호환 API 형식으로 호출을 표준화한다.
- 비즈니스 로직과 런타임 구현을 직접 결합하지 않는다.

초기 모델 전략:

- 대화용 모델 1개
- 코딩 또는 명령 해석용 모델 1개
- 필요 시 임베딩 모델 1개 추가

런타임 선택 기준:

- `Ollama`: 상시 운영, 단순한 배포, 자동 시작, 안정적인 서버형 사용에 유리
- `LM Studio`: 특정 GGUF 모델 테스트, 세밀한 로컬 실험, 모델별 체감 성능 비교에 유리
- `MLX`: Apple Silicon에서 MLX 계열 모델을 직접 서빙하기 좋고, 구조화 추출이나 코딩형 inference 분리에 유리

운영 권장안:

- MVP는 둘 중 하나만 우선 선택한다.
- 확장 단계에서는 설정값으로 런타임을 바꿀 수 있게 한다.
- 장기적으로는 요청 유형에 따라 런타임을 선택하는 구조까지 확장 가능하다.

예시 방향:

- 일반 대화: Qwen 3 8B 계열
- 코드/도구 성향: Qwen Coder 계열
- 임베딩: 선택한 런타임과 별도 운영 가능한 임베딩 모델

## 6. 외부 LLM 공급자

역할:

- 고난도 분석
- 복잡한 툴 사용 계획
- 로컬 모델 품질 보완

### 지원 프로바이더

| 프로바이더 | provider 값 | base_url 기본값 | 인증 방식 |
|-----------|-------------|-----------------|----------|
| OpenAI | `openai` | `https://api.openai.com/v1` | Bearer token |
| Anthropic (Claude) | `anthropic` | `https://api.anthropic.com` | `x-api-key` 헤더 |
| Google Gemini | `gemini` | `https://generativelanguage.googleapis.com` | URL query `key=` |

OpenAI 호환 서비스(Together, Groq, Fireworks 등)는 `provider=openai`로 `base_url`만 변경하면 동작한다.

### 동작 모드

| 환경변수 조합 | 채팅 | 구조화 추출 |
|-------------|------|-----------|
| `EXTERNAL_LLM_ENABLED=false` | 로컬 only | 로컬 only |
| `ENABLED=true`, `FALLBACK_ONLY=true` | 로컬 → 실패 시 외부 | 로컬 only |
| `ENABLED=true`, `FALLBACK_ONLY=false` | 외부 → 실패 시 로컬 | 로컬 only |
| `ENABLED=true`, `FALLBACK_ONLY=false`, `STRUCTURED_EXTRACTION_ENABLED=true` | 외부 → 로컬 | 외부 → 로컬 |

### 환경변수 예시

```env
# OpenAI
EXTERNAL_LLM_ENABLED=true
EXTERNAL_LLM_PROVIDER=openai
EXTERNAL_LLM_API_KEY=sk-...
EXTERNAL_LLM_MODEL=gpt-4o-mini
EXTERNAL_LLM_FALLBACK_ONLY=false

# Anthropic (Claude)
EXTERNAL_LLM_PROVIDER=anthropic
EXTERNAL_LLM_BASE_URL=https://api.anthropic.com
EXTERNAL_LLM_API_KEY=sk-ant-...
EXTERNAL_LLM_MODEL=claude-sonnet-4-20250514

# Google Gemini
EXTERNAL_LLM_PROVIDER=gemini
EXTERNAL_LLM_BASE_URL=https://generativelanguage.googleapis.com
EXTERNAL_LLM_API_KEY=AIza...
EXTERNAL_LLM_MODEL=gemini-2.5-flash

# 구조화 추출도 외부 LLM 사용
EXTERNAL_LLM_STRUCTURED_EXTRACTION_ENABLED=true
EXTERNAL_LLM_STRUCTURED_EXTRACTION_MODEL=gpt-4o  # 비워두면 EXTERNAL_LLM_MODEL 사용
```

외부 전송 전 정책:

- 민감정보 마스킹
- 사용자 승인 또는 정책 기반 허용
- 요청 로그 저장

## 7. 메시징 어댑터

### Slack

초기 권장:

- Slack Events API
- Bot token 기반 응답 전송

이유:

- 현재 FastAPI 단일 진입점 구조와 잘 맞는다.
- Kakao와 같은 webhook 계층으로 맞출 수 있다.
- 승인 티켓과 세션 저장 구조를 공통으로 재사용하기 쉽다.

주의:

- 실제 검증을 위해 공개 HTTPS URL과 Slack signing secret 설정이 필요하다.
- 향후 Socket Mode나 Slack Bolt worker를 추가하더라도 내부 공통 메시지 포맷은 유지한다.

### KakaoTalk

권장 방향:

- 카카오톡 공식 채널 사용
- OpenBuilder 또는 공식 webhook 연동
- FastAPI를 카카오 이벤트 수신과 서명 검증, 세션 정규화의 단일 진입점으로 사용

주의:

- 비공식 개인 계정 자동화는 운영 리스크와 정책 리스크가 크므로 제외한다.
- 공개 HTTPS는 Cloudflare Tunnel 공개 호스트를 기준으로 연결한다.
- 채널 기능과 챗봇 운영 기능을 구분해서 설계해야 한다.
- 카카오 응답 시간 제약을 고려해, 장기 작업은 비동기 작업 ID와 후속 알림 구조로 분리한다.

카카오 요청 처리 원칙:

- FastAPI는 카카오 payload를 내부 공통 메시지 포맷으로 변환한다.
- LangGraph는 의도 분류, 승인 필요 여부, 실행 경로를 결정한다.
- n8n은 Gmail, Calendar, Notion 같은 외부 자동화 실행을 담당한다.
- 카카오 채널에는 작업 접수, 진행 상태, 승인 요청, 완료 결과를 짧은 메시지로 반환한다.
- 자동화 계열 응답은 `basicCard`와 `quickReplies`를 우선 사용하고, 일반 답변은 `simpleText`로 유지한다.

## 8. Mac 자동화 계층

역할:

- 로컬 앱 조작
- 브라우저 상호작용
- 파일 및 시스템 작업

권장 우선순위:

1. AppleScript
2. Playwright
3. Open Interpreter

이유:

- AppleScript는 macOS 기본 앱과 통합이 좋다.
- Playwright는 웹 자동화에 안정적이다.
- Open Interpreter는 강력하지만 운영 리스크가 높다.

## 9. 세션 및 메모리 계층

역할:

- 사용자 식별 통합
- 채널별 세션과 공통 세션 연결
- 최근 대화 요약 유지
- 장기 메모리 저장과 검색
- 승인 대기 상태와 장기 작업 상태 추적

핵심 개념:

- `user_identity`: Slack, Kakao, Web 계정을 내부 사용자 ID에 매핑
- `channel_session`: 채널별 대화 단위
- `assistant_session`: 실제 작업 상태를 가지는 공통 세션
- `memory_item`: 선호, 사실, 절차, 반복 작업 패턴
- `approval_ticket`: 위험 작업 승인 대기 단위
- `task_run`: 장기 실행 작업 상태

기본 정책:

- 최근 대화는 원문과 요약을 함께 저장한다.
- 장기 메모리는 자동 저장이 아니라 분류 후 반영한다.
- 채널이 달라도 동일 사용자면 메모리를 재사용한다.
- 세션이 길어지면 요약본으로 압축하고 원문은 아카이브한다.

카카오를 주 채널로 둘 경우 추가 정책:

- `user_identity`는 카카오 사용자 식별자와 내부 사용자 ID를 우선 연결 기준으로 사용한다.
- 카카오 채널 대화는 짧은 왕복 메시지를 기본으로 보고, 장문 결과는 요약 후 필요 시 웹 UI나 외부 링크로 확장한다.
- 승인 요청은 카카오 카드형 응답 또는 링크 응답과 내부 승인 티켓을 함께 사용한다.

## 10. 스킬 계층

역할:

- 자주 쓰는 업무 능력을 재사용 가능한 단위로 제공
- 사용자 또는 워크스페이스별 기능 확장
- 프롬프트, 입력 스키마, 정책, 실행기 연결
- 외부 도구 서버(MCP)를 표준 인터페이스로 연결

예시 스킬:

- Gmail 요약 및 드래프트
- 일정 조정 제안
- 노션 회의록 등록
- 웹 조사 후 보고서 작성
- 경쟁사 가격 비교
- 맥 파일 정리

권장 구조:

- 스킬 메타데이터(SkillDescriptor): 스킬 ID, 도메인, 액션, 트리거 키워드, 입력 스키마, 실행기 유형, 승인 필요 여부
- 스킬 실행기 유형: n8n, macos, browser, mcp, local_function, api
- MCP 도구도 동일한 SkillDescriptor로 등록해 내부 스킬과 같은 인터페이스로 호출

상세 설계와 구현 로드맵은 [docs/plugin-and-skill-architecture.md](plugin-and-skill-architecture.md)에 정리한다.

## 카카오 중심 요청 흐름

```text
Kakao Channel/OpenBuilder
  -> FastAPI /api/kakao/webhook
  -> payload normalization
  -> session lookup or creation
  -> LangGraph route decision
      -> local_llm_path
      -> external_llm_path
      -> approval_path
      -> automation_path
  -> immediate Kakao response
  -> optional n8n workflow execution
  -> follow-up status or result message
```

핵심 판단 기준:

- 즉시 답변 가능한 요청은 로컬 LLM 우선 응답
- 승인 필요 작업은 승인 티켓 생성 후 대기
- 외부 SaaS 작업은 n8n workflow 호출로 분리
- 긴 작업은 접수 메시지와 후속 결과 메시지로 이원화
- 입력 파라미터 스키마
- 허용 채널 목록
- 필요한 권한과 승인 레벨
- 내부 실행기 연결 정보

## 데이터 저장소

### PostgreSQL

사용 목적:

- 사용자 프로필
- 대화 메타데이터
- 장기 메모리 인덱스
- 작업 이력
- 승인 요청 기록

### Redis

사용 목적:

- 캐시
- 세션 상태
- 작업 큐 (`assistant:tasks` LIST + `assistant:results:*` 키)
- LangGraph 체크포인트 보조 저장
- rate limiting (slowapi 연동)

## 요청 흐름

## OpenClaw 반영 후 전체 흐름

```text
User request from Web/Slack/Kakao
-> channel adapter normalization
-> identity resolution
-> assistant session load or create
-> recent summary and long-term memory load
-> LangGraph intent classification
-> route selection
  -> local answer
  -> external reasoning
  -> SaaS workflow
  -> browser automation
  -> macOS local action
-> local runtime selection (Ollama or LM Studio)
-> policy and approval evaluation
-> execution
-> result summary and channel formatting
-> transcript, task state, memory candidate save
```

### 일반 대화 흐름

```text
User input
-> Channel adapter
-> FastAPI normalization
-> LangGraph routing
-> local runtime selection
-> local LLM or external LLM
-> optional tool execution
-> response formatter
-> channel response
```

### 도구 실행 흐름

```text
User asks for action
-> LangGraph decides tool use
-> policy check
-> approval if needed
-> n8n or local automation execution
-> result normalization
-> final response
```

### 승인 흐름

```text
Action requested
-> risk classification
-> approval ticket created
-> user approves or rejects
-> execution resumes from saved state
```

### 채널 간 연속성 흐름

```text
User sends request from Slack
-> identity mapping finds internal user
-> assistant session already exists from Web UI
-> pending task and memory are loaded
-> agent continues same task in Slack context
-> response is formatted for Slack blocks
```

### 백그라운드 작업 흐름

```text
User requests long-running job
-> LangGraph creates task_run
-> execution delegated to n8n or worker
-> status stored in Redis/PostgreSQL
-> completion event triggers callback
-> user notified in original or preferred channel
```

### 비동기 Worker 큐 흐름

```text
Client sends POST /api/tasks/async { type, payload }
-> API publishes task to Redis LIST (assistant:tasks)
-> Worker BRPOP consumes task
-> Worker dispatches by type (chat, web_search, callback)
-> Result stored at assistant:results:{task_id} (TTL 600s)
-> Client polls GET /api/tasks/async/{task_id} for result
```

### 웹 검색 흐름

```text
User asks question requiring current information
-> Intent classified as web_search
-> Tavily API search (or browser-based Google search fallback)
-> Search results formatted as text context
-> LLM generates summary using search results
-> Final answer returned to user
```

### 브라우저 자동화 흐름

```text
User requests website-based action
-> intent classified as browser task
-> policy checks domain and action type
-> approval if login, purchase, message send, or destructive action
-> Playwright session starts
-> result snapshot and summary stored
-> final answer returned with evidence
```

### MCP 도구 실행 흐름

```text
MCP 서버가 MCP_SERVERS 설정에 정의됨
-> API 시작 시 MCPManager가 각 서버에 연결
-> list_tools()로 도구 목록을 발견
-> 발견된 도구를 SkillDescriptor로 변환하여 스킬 레지스트리에 등록
-> 사용자 메시지가 MCP 스킬에 매칭되면 intent=mcp_* 로 분류
-> LangGraph execute_mcp_tool 노드에서 call_tool() 호출
-> 결과를 텍스트로 변환하여 응답
```

설정 형식 (환경변수 MCP_SERVERS):
```json
[
  {"name": "macos", "transport": "stdio", "command": "python", "args": ["apps/macos-mcp-server/server.py"], "domain": "macos"},
  {"name": "filesystem", "transport": "sse", "url": "http://localhost:3001/sse"}
]
```

### 참조형 요청 · 후보 선택 흐름

```text
1. 사용자: "오늘 일정 보여줘"
   -> calendar_summary 실행 → 번호 매겨진 일정 목록 응답
   -> extract_candidates_from_reply()가 후보 목록 추출
   -> session_state.last_candidates에 저장

2. 사용자: "두 번째 삭제해줘"
   -> parse_ordinal_index()가 인덱스 1을 파싱
   -> last_candidates[1]의 라벨을 추출
   -> apply_reference_context()가 calendar payload에 주입
   -> calendar_delete 의도로 승인 흐름 진행
```

## 확장 후 가능한 기능

### 1. 채널 통합 개인 비서

- Web에서 시작한 작업을 Slack이나 Kakao에서 이어서 처리
- 채널별 UI 포맷은 달라도 같은 비서 상태 유지
- 승인 요청을 다른 채널에서 이어서 처리

### 2. 실행형 SaaS 자동화

- Gmail 읽기, 요약, 드래프트 생성
- Calendar 조회, 일정 충돌 확인, 일정 생성 제안
- Notion 페이지 생성, 회의록 저장, 작업 업데이트
- 정기 브리핑과 요약 자동 발송

### 3. 브라우저 및 조사 작업

- 특정 사이트 접속 후 정보 수집
- 여러 페이지 비교 후 요약 보고서 작성
- 로그인 필요한 내부 서비스의 제한적 자동화
- 스크린샷, HTML 요약, 주요 포인트 기록

### 4. macOS 로컬 작업

- Finder 파일 이동 및 정리
- Safari, Notes, Calendar 등 기본 앱 연동
- AppleScript 기반 반복 작업 자동화
- 고급 실험 단계에서 Open Interpreter 연계

### 5. 지속 메모리와 재사용 가능한 스킬

- 자주 쓰는 문체, 선호 보고 형식, 반복 작업 패턴 기억
- 업무 스킬을 조합해 복합 작업 처리
- 과거 승인 결과를 다음 정책 판단의 참고로 활용

### 6. 안전한 실행 통제

- 위험 작업 승인 필수화
- 모든 실행 결과에 감사 로그 저장
- 외부 LLM 전송 전 민감정보 마스킹
- 채널별 권한 차등 적용

## 단계별 필수 추가 항목

### MVP

- 공통 사용자 ID와 채널 매핑
- 공통 세션과 채널 세션 분리
- 승인 티켓 생성과 재개
- Slack 우선 채널 통합
- Ollama 또는 LM Studio 중 하나를 선택 가능한 구조
- Gmail 또는 Calendar 단일 자동화
- 메모리 후보 저장과 수동 검토 또는 단순 자동 반영

### 확장 단계

- Kakao 채널 연동
- Playwright 브라우저 작업 정식화
- 스킬 레지스트리
- 백그라운드 작업 큐
- 세션 요약과 메모리 압축
- 작업 완료 후 채널 알림

### 고급 단계

- 프로젝트별 권한 정책
- 브라우저 프로필 분리
- 서브에이전트 또는 작업 위임
- proactive 추천 또는 예약 실행 제안
- Open Interpreter 기반 고급 로컬 실행

## 상세 사용자 시나리오

### 1. 오늘 일정 요약

```text
Slack에서 "오늘 일정 정리해줘"
-> 사용자 식별
-> Calendar 조회 워크플로 호출
-> 오전/오후 일정 요약 생성
-> Slack 메시지로 응답
```

결과:

- 오늘 일정 요약
- 비는 시간 제안
- 필요 시 첫 회의 준비 메모 생성

### 2. 중요 메일만 요약

```text
Web UI에서 "중요 메일만 요약해줘"
-> Gmail 워크플로 실행
-> 중요도 분류
-> 메일별 핵심 포인트 요약
-> 요약 결과와 후속 액션 후보 제공
```

결과:

- 중요 메일 우선순위 목록
- 답장 필요 메일 표시
- 초안 작성 버튼 또는 후속 요청 가능

### 3. 메일 초안 작성 후 승인 요청

```text
"이 메일들에 답장 초안 작성해줘"
-> 메일 본문 불러오기
-> 초안 생성
-> 발송은 위험 액션으로 분류
-> approval_ticket 생성
-> 사용자 승인 후 실제 발송
```

결과:

- 발송 전 초안 검토
- 승인 후 자동 발송
- 감사 로그 저장

### 4. 회의 요약을 노션에 저장

```text
Slack에서 회의 요약 전달
-> Notion 저장 스킬 선택
-> 대상 데이터베이스 확인
-> 페이지 초안 생성
-> 승인 또는 자동 저장 정책 적용
```

결과:

- 회의록 페이지 생성
- 태그, 날짜, 담당자 자동 입력
- 관련 작업 항목 분리

### 5. 일정 충돌 확인 후 미팅 생성

```text
"내일 오후 김팀장과 30분 미팅 잡아줘"
-> Calendar availability 조회
-> 후보 시간 계산
-> 사용자 확인
-> 이벤트 생성 승인
-> 일정 등록
```

결과:

- 가능한 시간 제안
- 승인 후 일정 생성
- 필요 시 초대 메시지 초안 생성

### 6. 웹 조사 후 요약 보고서 작성

```text
"세 개 서비스 가격 비교 조사해줘"
-> browser research route
-> Playwright 또는 웹 검색 수행
-> 정보 비교표 작성
-> 최종 요약과 추천안 생성
```

결과:

- 가격 비교표
- 핵심 차이점
- 추천안과 근거

### 7. 로그인 필요한 사이트에서 정보 수집

```text
"관리자 페이지에서 이번 주 가입자 수 확인해줘"
-> 도메인 허용 정책 확인
-> 로그인 필요 작업으로 분류
-> 승인 요청
-> 브라우저 세션 실행
-> 수치 추출 후 응답
```

결과:

- 승인 기반 브라우저 실행
- 결과 수치와 캡처 저장
- 후속 분석 가능

### 8. 맥 로컬 파일 정리

```text
"다운로드 폴더 PDF를 프로젝트별로 정리해줘"
-> 파일 작업 분류
-> 미리보기 계획 제시
-> 승인 요청
-> AppleScript 또는 로컬 스크립트 실행
-> 결과 요약
```

결과:

- 실행 전 계획 확인
- 승인 후 파일 이동
- 변경 이력 저장

### 9. 웹에서 시작한 작업을 Slack에서 이어가기

```text
Web에서 조사 작업 시작
-> assistant_session 저장
-> Slack에서 "방금 작업 이어서 보고서 마무리해줘"
-> 기존 task_run 로드
-> 이어서 결과 정리
-> Slack으로 응답
```

결과:

- 채널 이동 후에도 문맥 유지
- 같은 작업 ID 기준 추적
- 중복 지시 감소

### 10. 매일 아침 브리핑 자동 생성

```text
사용자가 아침 브리핑 스킬 활성화
-> n8n scheduler 또는 worker cron 등록
-> Gmail, Calendar, Notion 데이터 집계
-> 요약 생성
-> 지정 채널로 자동 전달
```

결과:

- 매일 일정, 중요 메일, 전날 미완료 업무 요약
- 채널별 맞춤 포맷 응답
- 필요 시 바로 후속 액션 연결

## 보안 초안

최소 보안 기준:

- HTTPS 강제
- Ollama 포트 외부 미노출
- API 키는 환경변수 또는 시크릿 스토어에 저장
- Slack/Kakao 서명 검증
- 승인 없는 위험 작업 금지
- 모든 외부 액션에 감사 로그 기록

## 운영 및 복구 전략

현재 권장 구조는 단일 맥미니 기반 self-hosted 운영이므로, 장애 대응은 멀티노드 고가용성보다 `빠른 탐지`, `안전한 재기동`, `상태 복구`, `백업 복원`에 초점을 둔다.

### 복구 목표

- 서비스 중단 시 핵심 채팅 경로를 우선 복구한다.
- 승인 대기 작업과 장기 작업 상태를 최대한 유실 없이 복원한다.
- 데이터 손실 범위를 사전에 정의하고 백업 주기로 통제한다.
- 로컬 LLM 런타임 장애가 나도 코어 API와 데이터 계층은 보호한다.

### 단일 장비 운영의 핵심 리스크

- 맥 재부팅 또는 절전으로 전체 서비스 중단
- SSD 부족으로 데이터베이스, 로그, 모델 로딩 실패
- 로컬 LLM 런타임 다운으로 응답 경로 일부 중단
- Playwright 또는 브라우저 작업 폭주로 시스템 자원 고갈
- 잘못된 배포나 설정 변경으로 전체 서비스 장애

### 백업 대상

필수 백업 대상:

- PostgreSQL 데이터베이스
- Redis에만 존재하면 안 되는 승인 티켓과 작업 상태의 영속 저장본
- n8n workflow 및 credential export
- `.env`와 시크릿 관리 파일
- 프롬프트, 스킬 정의, 정책 파일
- 사용자 업로드 파일과 핵심 산출물 메타데이터

선택 백업 대상:

- 대화 원문과 요약 아카이브
- 브라우저 작업 스크린샷과 HTML 스냅샷
- 감사 로그 장기 보관본

백업 원칙:

- 데이터베이스는 일 단위 스냅샷과 최근 백업 보존 정책을 둔다.
- 설정 파일과 워크플로는 Git 또는 별도 암호화 백업으로 관리한다.
- 대용량 로그와 브라우저 산출물은 서비스 데이터와 분리한다.
- 백업은 같은 내부 디스크만이 아니라 외장 SSD 또는 원격 저장소에도 복제한다.

### 상태 복구 원칙

- 승인 티켓은 PostgreSQL에 저장하고 Redis는 보조 캐시로만 사용한다.
- LangGraph 체크포인트와 `task_run`은 재시작 후 재개 가능해야 한다.
- n8n이 호출한 장기 작업은 idempotency key 또는 작업 ID 기반으로 중복 실행을 방지한다.
- 브라우저 자동화는 재시작 후 무조건 이어붙이기보다 실패 처리 후 재시도 가능한 구조가 안전하다.

### 서비스 재기동 순서

장애 후 기본 재기동 순서는 아래가 적절하다.

```text
1. PostgreSQL
2. Redis
3. Local LLM Runtime (Ollama or LM Studio)
4. n8n
5. FastAPI
6. LangGraph worker
7. Open WebUI
8. Browser runner / local automation worker
```

이유:

- 데이터 저장소가 먼저 살아야 상태 복구가 가능하다.
- 로컬 추론 런타임이 살아 있어야 API의 기본 응답 경로가 열린다.
- Open WebUI는 가장 마지막에 붙여도 무방하다.

### 장애 유형별 대응 초안

#### 1. 로컬 LLM 런타임 장애

증상:

- 로컬 응답만 실패하고 API는 살아 있음
- Open WebUI 또는 FastAPI에서 모델 호출 타임아웃 발생

대응:

- Ollama 또는 LM Studio 프로세스 상태 확인
- 디스크 여유 공간과 메모리 사용량 확인
- 모델 재로딩 또는 런타임 재시작
- 필요 시 외부 LLM 임시 fallback 활성화

#### 2. PostgreSQL 장애

증상:

- 세션 조회, 승인 처리, 작업 재개 실패
- API가 일부 또는 전체 요청에서 오류 반환

대응:

- 데이터베이스 정상 기동 우선
- 마지막 정상 백업 시점 확인
- 불가피하면 read-only 모드로 일시 전환
- 승인 재개와 장기 작업은 DB 복구 후 재개

#### 3. Redis 장애

증상:

- 캐시, 큐, 일부 실시간 상태 조회 장애

대응:

- 핵심 상태는 PostgreSQL 기준으로 복원
- Redis 재기동 후 큐 소비기 재연결
- 임시로 비핵심 기능 비활성화 가능

#### 4. n8n 장애

증상:

- Gmail, Calendar, Notion 자동화 실패

대응:

- 워크플로와 credential export 복원 가능 여부 확인
- 실패 작업은 `task_run`에 재시도 가능 상태로 남긴다.
- 코어 채팅 경로는 n8n 없이도 동작 가능하게 유지한다.

#### 5. 브라우저 자동화 장애

증상:

- Playwright 작업만 실패
- 특정 사이트 자동화만 비정상

대응:

- 해당 작업을 실패 처리 후 수동 재시도
- 로그인 세션과 도메인 정책 확인
- 브라우저 러너를 메인 API와 분리해 장애 전파를 막는다.

#### 6. 잘못된 배포 또는 설정 변경

증상:

- 업데이트 직후 전체 기능 이상

대응:

- 직전 설정 파일과 compose 설정으로 롤백
- 이미지 태그 또는 패키지 버전을 고정 사용
- 프로덕션 반영 전 테스트 환경 또는 dev profile로 검증

### 운영 모니터링 최소 기준

- FastAPI `/api/health` 헬스체크
- PostgreSQL 연결 상태 확인
- Redis 연결 상태 확인
- 로컬 LLM 런타임 응답 확인
- 디스크 사용량 임계치 알림
- 메모리 사용량 임계치 알림
- n8n workflow 실패 알림

### 권장 복구 절차

```text
1. 장애 범위 확인
2. 데이터 계층 상태 확인
3. 로컬 LLM 런타임 상태 확인
4. FastAPI 및 worker 로그 확인
5. 필요한 서비스만 순차 재기동
6. 승인 티켓과 task_run 복구 여부 확인
7. 브라우저 및 자동화 작업 재시도 여부 판단
8. 정상화 후 원인 기록 및 재발 방지 반영
```

### 구현 전 추가 결정 항목

- 백업 주기와 보관 기간
- 외장 SSD 또는 원격 백업 사용 여부
- 맥 재부팅 후 자동 시작 정책의 profile 범위
- 외부 LLM fallback 허용 범위
- 장애 시 read-only 모드 지원 여부
- 로그와 브라우저 산출물의 삭제 주기

## 배포 초안

초기 권장 배포는 단일 맥미니 기반 self-hosted 구성을 전제로 한다.

```text
Mac mini
├── Caddy/Nginx
├── Open WebUI
├── FastAPI
├── LangGraph worker
├── n8n
├── Redis
├── PostgreSQL
└── Ollama
```

배포 방식 초안:

- Docker Compose 중심 운영
- 데이터 볼륨 분리
- 로그 및 백업 경로 분리
- Kakao 공개 ingress는 Cloudflare Tunnel에서 reverse proxy로 연결
- 운영자 UI, n8n, SSH는 Tailscale tailnet으로만 접근

## Docker 기반 운영 전략

현재 구조에서는 Docker를 기본 배포 방식으로 쓰는 것이 적절하다. 다만 macOS 네이티브 제어와 로컬 LLM 런타임 특성상, 모든 것을 컨테이너에 넣기보다 `컨테이너 계층`과 `호스트 계층`을 분리하는 편이 안정적이다.

### 1. 컨테이너 계층과 호스트 계층 분리

권장 분리는 아래와 같다.

컨테이너 계층:

- reverse proxy
- cloudflared 선택 프로필
- Open WebUI
- FastAPI
- LangGraph worker
- n8n
- PostgreSQL
- Redis
- 선택적 Playwright runner

호스트 계층:

- Ollama 또는 LM Studio
- AppleScript 실행기
- macOS 앱 제어 워커
- Open Interpreter 실험 환경

핵심 이유:

- Docker는 서비스 간 의존성 관리와 재기동, 버전 고정, 볼륨 백업에 유리하다.
- AppleScript와 Finder, Safari, Notes, Calendar 같은 macOS 앱 제어는 호스트 권한이 더 자연스럽다.
- LM Studio는 macOS 앱 중심 운영 흐름이 강하므로 호스트에서 띄우는 편이 낫다.

### 2. 서비스 분리 기준

서비스 분리는 아래 기준으로 잡는 것이 좋다.

- `api`: 채널 입력, 인증, 정규화, 정책 적용
- `worker`: LangGraph 상태 실행, 장기 작업, 승인 후 재개
- `webui`: 사용자 운영 UI
- `n8n`: 외부 SaaS 실행과 스케줄
- `db`: PostgreSQL
- `cache`: Redis
- `proxy`: HTTPS와 라우팅
- `browser-runner`: 선택적 브라우저 자동화 전용 실행기

현재 `browser-runner`는 Playwright 기반 read-only 추출 엔드포인트 `/browse/read`를 제공하고, FastAPI는 이를 `/assistant/api/browser/read` 경로로 프록시한다.

macOS 자동화는 호스트 프로세스 `macos_runner`가 맡고, 현재는 `POST /macos/notes` 내부 엔드포인트를 통해 Notes 앱에 메모를 생성한다. FastAPI는 승인된 요청에 한해 이 호스트 runner를 호출한다.

이 기준을 지키면 API 장애와 브라우저 자동화 장애를 분리하기 쉽고, 장기 작업을 웹 요청과 분리할 수 있다.

### 3. 네트워크 연결 원칙

- 컨테이너 내부 서비스는 내부 네트워크 이름으로 통신한다.
- FastAPI와 worker는 PostgreSQL, Redis, n8n에 내부 네트워크로 접근한다.
- Ollama 또는 LM Studio는 호스트에서 실행하고, 컨테이너는 호스트 주소를 통해 접근한다.
- Kakao 공개 경로는 Cloudflare Tunnel에서 `proxy:80`으로 연결하고, 실제 공개 URL은 `/assistant/api/kakao/webhook`를 사용한다.
- 운영자용 Open WebUI, n8n, SSH는 Tailscale tailnet 경로로만 접근한다.
- 홈 라우터 포트포워딩으로 Open WebUI, n8n, SSH를 직접 공개하지 않는다.

### 4. 볼륨 분리 원칙

반드시 독립 볼륨 또는 디렉터리로 분리할 대상:

- PostgreSQL 데이터
- Redis 지속 데이터가 필요한 경우의 저장소
- Open WebUI 데이터
- n8n 데이터
- Caddy 인증서와 설정
- 로그와 백업 디렉터리

권장 추가 분리 대상:

- 브라우저 산출물
- 업로드 파일
- 스냅샷 및 감사 로그 아카이브

### 5. 버전 관리 원칙

- `latest` 대신 고정 버전 태그 사용
- Open WebUI, PostgreSQL, Redis, n8n은 버전 고정
- 롤백을 위해 직전 compose 파일과 환경변수 세트를 보관
- dev 실험용 프로필과 운영 프로필을 분리

## Docker Compose 초안

아래는 현재 아키텍처에 맞는 개념적 초안이다.

```yaml
services:
  proxy:
    image: caddy:<PINNED_VERSION>
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infra/caddy/Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - webui
      - api

  cloudflared:
    image: cloudflare/cloudflared:<PINNED_VERSION>
    command: tunnel --no-autoupdate run --token ${CLOUDFLARE_TUNNEL_TOKEN}
    profiles:
      - edge
    depends_on:
      - proxy

  webui:
    image: ghcr.io/open-webui/open-webui:<PINNED_VERSION>
    environment:
      - OPENAI_API_BASE_URL=http://api:8000
    volumes:
      - openwebui_data:/app/backend/data
    depends_on:
      - api

  api:
    build:
      context: ./apps/api
    env_file:
      - .env
    environment:
      - DATABASE_URL=postgresql://app:app@postgres:5432/assistant
      - REDIS_URL=redis://redis:6379/0
      - N8N_BASE_URL=http://n8n:5678
      - LOCAL_LLM_BASE_URL=http://host.docker.internal:<LOCAL_LLM_PORT>/v1
    depends_on:
      - postgres
      - redis
      - n8n

  worker:
    build:
      context: ./apps/workers
    env_file:
      - .env
    environment:
      - DATABASE_URL=postgresql://app:app@postgres:5432/assistant
      - REDIS_URL=redis://redis:6379/0
      - LOCAL_LLM_BASE_URL=http://host.docker.internal:<LOCAL_LLM_PORT>/v1
    depends_on:
      - postgres
      - redis

  n8n:
    image: n8nio/n8n:<PINNED_VERSION>
    env_file:
      - .env
    volumes:
      - n8n_data:/home/node/.n8n
    depends_on:
      - postgres

  postgres:
    image: postgres:<PINNED_VERSION>
    environment:
      - POSTGRES_DB=assistant
      - POSTGRES_USER=app
      - POSTGRES_PASSWORD=app
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:<PINNED_VERSION>
    volumes:
      - redis_data:/data

  browser-runner:
    build:
      context: ./apps/browser-runner
    profiles:
      - browser
    shm_size: "1gb"
    depends_on:
      - api

volumes:
  caddy_data:
  caddy_config:
  openwebui_data:
  n8n_data:
  postgres_data:
  redis_data:
```

### Compose 초안 해설

- `proxy`는 로컬 reverse proxy 역할만 맡고, Kakao 공개 ingress는 Cloudflare Tunnel이 이 컨테이너로 연결한다.
- `cloudflared`는 선택 프로필로 두고 Kakao 공개 hostname만 Cloudflare에서 연결한다.
- `api`와 `worker`는 같은 환경변수를 공유하되 실행 책임을 분리한다.
- `LOCAL_LLM_BASE_URL`은 일반 응답용 호스트 런타임을 가리킨다.
- `LOCAL_LLM_STRUCTURED_EXTRACTION_BASE_URL`은 구조화 추출 전용 런타임을 별도로 가리킬 수 있다.
- `browser-runner`는 기본값이 아니라 선택 프로필로 두는 편이 안전하다.
- PostgreSQL과 n8n 데이터는 반드시 볼륨으로 분리한다.
- 외부 프록시 경로는 `Open WebUI=/`, `FastAPI=/assistant/api/*`처럼 분리해 Open WebUI의 자체 `/api`와 충돌하지 않게 한다.
- Open WebUI, n8n, SSH 같은 운영자 경로는 Tailscale tailnet hostname으로만 접근한다.

### Docker 적용 시 주의사항

- `host.docker.internal` 접근 가능 여부를 macOS 환경에서 실제 검증해야 한다.
- LM Studio를 사용할 경우 OpenAI 호환 API 포트와 자동 시작 정책을 확인해야 한다.
- MLX를 사용할 경우 `mlx_lm.server --model <repo> --port <port>` 형태로 호스트에서 OpenAI 호환 HTTP 서버를 띄우고, FastAPI는 `host.docker.internal` 경유로 접근한다.
- AppleScript 실행기는 컨테이너 안이 아니라 호스트 프로세스로 두는 편이 낫다.
- Playwright는 브라우저 자원 사용량이 커서 API와 같은 컨테이너에 넣지 않는 편이 안전하다.
- 로그 디렉터리를 컨테이너 데이터와 분리해 디스크 폭주를 막아야 한다.

OpenClaw 계열 기능까지 반영하면 아래 컴포넌트가 추가로 중요해진다.

- session worker 또는 background worker
- approval store
- skills registry
- browser runner
- audit log pipeline

운영 단계에서는 아래 항목도 함께 고려한다.

- backup runner
- health check runner
- restore procedure 문서
- version-pinned deployment 설정

## 권장 저장소 구조

```text
apps/
  api/
  workers/
packages/
  agent-core/
  channel-adapters/
  automation-clients/
  policies/
  prompts/
infra/
  docker/
  caddy/
  scripts/
workflows/
  n8n/
docs/
  architecture.md
```

## 구현 전 즉시 결정할 항목

구현 전에 아래 항목을 확정하는 것이 좋다.

1. 로컬 주력 모델 2개 선정
2. 외부 LLM 공급자 1개 선정
3. 승인 정책 범위 정의
4. n8n을 같은 머신에 둘지 분리할지 결정
5. Kakao는 OpenBuilder 중심인지 직접 webhook 중심인지 결정
6. 채널 간 동일 사용자 식별 규칙 정의
7. 메모리 자동 저장 기준 정의
8. 브라우저 작업 허용 도메인 정책 정의
9. 스킬 등록 방식과 배포 단위 정의
10. 백업 및 복구 정책 정의
11. 맥 재부팅 후 자동 시작 순서 정의

현재 기본 운영안에서는 아래 순서를 채택한다.

- launchd `com.aiassistant.mlx-base-server`
- launchd `com.aiassistant.mlx-webui-proxy`
- launchd `com.aiassistant.stack`

`com.aiassistant.stack` 는 Docker Desktop 준비를 기다린 뒤 Compose core stack을 재기동한다.

## MVP 범위 권장안

가장 작은 MVP 범위는 아래다.

- Open WebUI + Ollama 또는 LM Studio 연결
- FastAPI 공통 API
- LangGraph 최소 라우터
- Slack Socket Mode
- n8n으로 Gmail 또는 Calendar 중 하나만 연결
- 승인 기반 액션 1개 구현
- PostgreSQL 백업과 서비스 재기동 절차 문서화

MVP 이후 바로 이어서 넣을 권장 항목:

- 공통 세션과 채널 매핑 테이블
- 승인 티켓 조회 API
- 작업 상태 조회 API
- 기본 메모리 저장 정책
- 브라우저 자동화 1개 read-only 시나리오
- 장애 알림과 디스크 사용량 모니터링

이 범위를 넘기기 전에는 Kakao와 Mac 자동화를 동시에 넣지 않는 것이 좋다.