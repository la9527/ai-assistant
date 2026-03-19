# 플러그인 및 스킬 확장 아키텍처

## 목적

현재 AI Assistant는 `automation.py` 단일 파일에 의도 분류, 파라미터 추출, 실행 라우팅이 모두 들어 있다.
새 자동화 기능을 추가할 때마다 이 파일의 복잡도가 선형으로 증가하고, 도메인 간 결합이 강해져 유지보수가 어렵다.

이 문서는 향후 기능을 **플러그인(스킬)** 단위로 분리하고, **MCP(Model Context Protocol)** 도구 서버를 외부 확장점으로 연결할 수 있는 구조를 설계한다.

핵심 원칙:

- 현재 동작하는 코드를 깨지 않으면서 점진적으로 전환한다.
- 스킬 하나가 하나의 자동화 능력을 완결적으로 기술한다.
- 외부 도구 서버(MCP)와 내부 스킬이 같은 인터페이스로 LangGraph 노드에 노출된다.

---

## 1. 현재 구조와 한계

### 현재 흐름

```text
사용자 메시지
  → automation.classify_message_intent()   # 키워드 기반 의도 분류
  → automation.extract_structured_request() # 규칙 + LLM 추출
  → automation.process_message()           # n8n/macOS/LLM 라우팅 + 승인
  → 응답
```

### 한계

| 문제 | 설명 |
|------|------|
| **단일 파일 집중** | 의도 분류, 추출, 라우팅, 실행이 `automation.py` 한 곳에 혼재 |
| **하드코딩된 의도** | 새 기능 추가 시 키워드 튜플과 분기 조건을 직접 수정해야 함 |
| **도구 확장 불가** | 외부 도구 서버(MCP 등)를 연결할 인터페이스 없음 |
| **재사용 어려움** | calendar, mail, note 로직을 다른 워크플로에서 독립 호출 불가 |
| **테스트 어려움** | 전체 파이프라인을 거쳐야 개별 기능 검증 가능 |

---

## 2. 목표 구조 개요

```text
사용자 메시지
  → LangGraph StateGraph
      → classify_intent 노드 (스킬 레지스트리 참조)
      → select_skill 노드
      → extract_params 노드 (스킬별 추출기)
      → validate 노드
      → approve_if_needed 노드
      → execute 노드 (스킬 실행기 또는 MCP 도구 호출)
      → respond 노드
```

### 핵심 변화

1. **스킬 레지스트리**: 자동화 능력을 `SkillDescriptor` 단위로 등록
2. **MCP 도구 서버**: 외부 도구를 MCP 프로토콜로 연결해 동일 인터페이스로 호출
3. **LangGraph 통합**: 스킬과 MCP 도구 모두 그래프 노드에서 실행

---

## 3. 스킬 레지스트리 설계

### 3-1. SkillDescriptor 스키마

```python
from pydantic import BaseModel
from typing import Literal


class SkillDescriptor(BaseModel):
    """하나의 자동화 능력을 기술하는 메타데이터."""
    skill_id: str                          # 예: "calendar_create"
    name: str                              # 사람용 이름: "일정 생성"
    description: str                       # LLM 의도 분류 시 참조할 설명
    domain: str                            # calendar, mail, note, browser, macos, search ...
    action: str                            # create, delete, summarize, read ...
    trigger_keywords: list[str]            # 한국어/영어 트리거 힌트
    input_schema: dict                     # JSON Schema (Pydantic model export)
    output_schema: dict | None = None
    executor_type: Literal[
        "n8n", "macos", "browser", "mcp", "local_function"
    ]
    executor_ref: str                      # n8n webhook 경로, MCP 도구 이름 등
    approval_required: bool = False        # 승인 필요 여부
    risk_level: Literal["low", "medium", "high"] = "low"
    allowed_channels: list[str] = ["web", "slack", "kakao"]
    enabled: bool = True
```

### 3-2. 레지스트리 운영 방식

| 단계 | 저장 형태 | 설명 |
|------|-----------|------|
| **MVP** | Python 코드 내 정적 목록 | `app/skills/registry.py`에 `SKILL_REGISTRY: list[SkillDescriptor]` |
| **확장** | YAML/JSON 파일 | `skills/*.yaml` 파일로 분리, 서버 재시작 시 로드 |
| **고급** | PostgreSQL + 관리 UI | DB 저장, 런타임 추가/제거, 관리자 페이지에서 편집 |

### 3-3. 의도 분류와 스킬 매칭

현재 키워드 기반 분류를 유지하되, 스킬 레지스트리를 입력으로 사용한다.

```text
1. 사용자 메시지에서 스킬별 trigger_keywords 매칭 (빠른 필터)
2. 매칭 후보가 2개 이상이면 LLM에 스킬 description 목록을 제공해 최종 선택
3. 매칭 후보가 0개면 일반 대화(chat)로 분류
```

이후 LangGraph 전환 시 `classify_intent` 노드가 이 로직을 담당하고, 스킬 레지스트리를 도구 목록으로 참조한다.

---

## 4. MCP (Model Context Protocol) 통합 설계

### 4-1. MCP란

MCP는 LLM 애플리케이션이 외부 도구·데이터 소스에 표준 프로토콜로 접근하는 오픈 프로토콜이다.
MCP 서버는 `tools`, `resources`, `prompts` 세 가지를 노출하고, MCP 클라이언트가 이를 호출한다.

```text
AI Assistant (MCP 클라이언트)
  ↔ MCP 프로토콜 (JSON-RPC over stdio/SSE/streamable-http)
    ↔ MCP 서버 A (파일 시스템 도구)
    ↔ MCP 서버 B (GitHub 도구)
    ↔ MCP 서버 C (사내 API 래퍼)
```

### 4-2. 도입 목적

| 목적 | 설명 |
|------|------|
| **외부 도구 확장** | GitHub, Notion, Jira 등 커뮤니티 MCP 서버를 코드 수정 없이 연결 |
| **도구 격리** | MCP 서버는 별도 프로세스로 실행, 장애 시 메인 API에 영향 없음 |
| **표준화** | 도구 호출 인터페이스를 MCP 표준으로 통일해 재사용성 향상 |
| **보안 경계** | MCP 서버별 권한·접근 범위를 분리 관리 가능 |

### 4-3. MCP 아키텍처 통합

```text
┌─────────────────────────────────────────┐
│              FastAPI + LangGraph         │
│                                         │
│  classify → select_skill → execute      │
│                │                        │
│    ┌───────────┴────────────┐          │
│    ▼                        ▼          │
│  내부 스킬 실행기        MCP 클라이언트  │
│  (n8n, macOS, browser)   (mcp 라이브러리)│
│                             │          │
└─────────────────────────────┼──────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         MCP 서버 A      MCP 서버 B      MCP 서버 C
         (filesystem)    (github)        (custom)
```

### 4-4. MCP 클라이언트 통합 계획

**Phase 1: 기반 준비**

```python
# app/mcp/client.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClientManager:
    """MCP 서버 연결을 관리하는 클라이언트 매니저."""

    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}

    async def connect(self, server_id: str, params: StdioServerParameters):
        """MCP 서버에 연결하고 세션을 유지한다."""
        ...

    async def list_tools(self, server_id: str) -> list[dict]:
        """특정 MCP 서버가 제공하는 도구 목록을 반환한다."""
        ...

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> dict:
        """MCP 서버의 도구를 호출하고 결과를 반환한다."""
        ...

    async def disconnect(self, server_id: str):
        """MCP 서버 연결을 종료한다."""
        ...
```

**Phase 2: MCP 서버 설정 파일**

```yaml
# config/mcp-servers.yaml
servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/user/Documents"]
    enabled: true
    trust_level: "read_only"

  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
    enabled: true
    trust_level: "read_write"

  brave-search:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-brave-search"]
    env:
      BRAVE_API_KEY: "${BRAVE_API_KEY}"
    enabled: false
    trust_level: "read_only"
```

**Phase 3: LangGraph 도구 노드 통합**

MCP 도구와 내부 스킬을 같은 `execute` 노드에서 호출할 수 있도록 통합한다.

```python
async def execute_node(state: GraphState) -> GraphState:
    skill = state["selected_skill"]

    if skill.executor_type == "mcp":
        result = await mcp_manager.call_tool(
            server_id=skill.executor_ref.split("/")[0],
            tool_name=skill.executor_ref.split("/")[1],
            arguments=state["extracted_params"],
        )
    elif skill.executor_type == "n8n":
        result = await call_n8n_webhook(skill.executor_ref, state["extracted_params"])
    elif skill.executor_type == "macos":
        result = await call_macos_runner(skill.executor_ref, state["extracted_params"])
    elif skill.executor_type == "browser":
        result = await call_browser_runner(state["extracted_params"])
    elif skill.executor_type == "local_function":
        result = await call_local_function(skill.executor_ref, state["extracted_params"])

    state["execution_result"] = result
    return state
```

### 4-5. MCP 도입 후보 서버

| MCP 서버 | 용도 | 우선순위 |
|----------|------|----------|
| `@modelcontextprotocol/server-filesystem` | 로컬 파일 읽기/쓰기/정리 | 높음 |
| `@modelcontextprotocol/server-brave-search` | 웹 검색 | 높음 |
| `@modelcontextprotocol/server-github` | GitHub 이슈/PR 관리 | 중간 |
| `@anthropic/server-fetch` | 웹 페이지 가져오기 | 중간 |
| 커스텀 MCP 서버 (macOS 제어) | AppleScript 실행 래핑 | 높음 (자체 구현) |
| 커스텀 MCP 서버 (Photos) | macOS Photos 앱 연동 | 중간 (자체 구현) |

---

## 5. 내부 스킬 모듈 구조

현재 `automation.py`에 혼재된 로직을 도메인별 스킬 모듈로 분리한다.

### 5-1. 디렉터리 구조

```text
apps/api/app/
├── skills/
│   ├── __init__.py
│   ├── registry.py          # SkillDescriptor 목록 + 매칭 로직
│   ├── base.py              # BaseSkill 추상 클래스
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── descriptor.py    # calendar 스킬 메타데이터
│   │   ├── extractor.py     # calendar 파라미터 추출
│   │   └── executor.py      # n8n webhook 호출
│   ├── mail/
│   │   ├── __init__.py
│   │   ├── descriptor.py
│   │   ├── extractor.py
│   │   └── executor.py
│   ├── note/
│   │   ├── __init__.py
│   │   ├── descriptor.py
│   │   ├── extractor.py
│   │   └── executor.py
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── descriptor.py
│   │   └── executor.py
│   └── search/
│       ├── __init__.py
│       ├── descriptor.py
│       └── executor.py       # MCP brave-search 또는 직접 호출
├── mcp/
│   ├── __init__.py
│   ├── client.py             # MCPClientManager
│   └── config.py             # MCP 서버 설정 로드
├── graph/
│   ├── __init__.py
│   ├── state.py              # GraphState 정의
│   ├── nodes.py              # LangGraph 노드 함수
│   └── workflow.py           # StateGraph 조립
└── automation.py             # (레거시, 점진 축소)
```

### 5-2. BaseSkill 인터페이스

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel


class BaseSkill(ABC):
    """모든 스킬이 구현하는 공통 인터페이스."""

    @abstractmethod
    def descriptor(self) -> SkillDescriptor:
        """스킬 메타데이터를 반환한다."""
        ...

    @abstractmethod
    async def extract(self, message: str, context: dict) -> BaseModel:
        """사용자 메시지에서 실행에 필요한 파라미터를 추출한다."""
        ...

    @abstractmethod
    async def validate(self, params: BaseModel) -> list[str]:
        """추출된 파라미터의 유효성을 검증하고 누락 필드를 반환한다."""
        ...

    @abstractmethod
    async def execute(self, params: BaseModel) -> dict:
        """실제 작업을 실행하고 결과를 반환한다."""
        ...
```

### 5-3. 스킬 등록 예시

```python
# app/skills/calendar/descriptor.py
from app.skills.registry import SkillDescriptor

CALENDAR_CREATE_SKILL = SkillDescriptor(
    skill_id="calendar_create",
    name="일정 생성",
    description="Google Calendar에 새 일정을 추가한다. 날짜, 시간, 제목이 필요하다.",
    domain="calendar",
    action="create",
    trigger_keywords=["일정", "캘린더", "추가", "생성", "등록", "만들", "잡아"],
    input_schema=CalendarExtractionPayload.model_json_schema(),
    executor_type="n8n",
    executor_ref="/webhook/assistant-calendar-create",
    approval_required=True,
    risk_level="medium",
)
```

---

## 6. 전환 로드맵

### Phase 1: 스킬 레지스트리 + 모듈 분리 🔧 진행 중

LangGraph 도입 전에 가능하다.

- [x] `app/skills/` 디렉터리 생성
- [x] `SkillDescriptor` 스키마와 `BaseSkill` 추상 클래스 정의
- [x] calendar, mail, note 기존 로직을 스킬 모듈로 이동 (기존 동작 유지)
- [x] `automation.py`에서 스킬 레지스트리를 참조해 의도 분류
- [x] 기존 키워드 분류 결과와 레지스트리 분류 결과를 비교 검증

**결과**: `automation.py` 크기 절반 이하로 축소, 새 스킬 추가 시 파일 하나만 만들면 됨

### Phase 2: LangGraph StateGraph 전환 🔧 진행 중

- [x] `app/graph/` 디렉터리 생성
- [x] `AssistantState`와 노드 함수 정의
- [x] `classify → validate → (route) → check_approval → execute` 그래프 조립
- [x] `process_message()`에서 그래프 실행 우선, legacy fallback 유지
- [ ] 승인 대기 → 재개 흐름을 그래프 interrupt/resume으로 전환

**결과**: 요청 흐름이 명시적 그래프로 시각화 가능, 상태 추적 자연스러움

### Phase 3: MCP 클라이언트 통합 ⬜ 미착수

- [ ] `app/mcp/` 디렉터리 생성
- [ ] `MCPClientManager` 구현
- [ ] `config/mcp-servers.yaml` 설정 파일 추가
- [ ] MCP 도구를 `SkillDescriptor(executor_type="mcp")`로 등록
- [ ] `execute` 노드에서 MCP 호출 경로 추가
- [ ] Brave Search MCP 서버를 첫 외부 도구로 연결해 검증

**결과**: 외부 MCP 서버를 설정 파일만으로 추가 가능

### Phase 4: 사용자 정의 MCP 서버 ⬜ 미착수

- [ ] macOS 제어 MCP 서버 (AppleScript 실행 래퍼)
- [ ] Photos 앱 MCP 서버 (앨범/사진 관리)
- [ ] 파일 정리 MCP 서버 (Finder 작업)

**결과**: macOS 호스트 자동화를 MCP 서버로 격리, Worker/API와 독립 배포

---

## 7. MCP 보안 정책

MCP 서버는 외부 프로세스이므로 보안 경계를 명확히 한다.

### 7-1. 신뢰 수준 분류

| 수준 | 설명 | 예시 |
|------|------|------|
| `read_only` | 읽기만 허용 | 파일 읽기, 웹 검색 |
| `read_write` | 읽기/쓰기 허용, 승인 정책 적용 | GitHub PR, 파일 쓰기 |
| `system` | 시스템 수준 작업, 반드시 승인 필요 | 프로세스 실행, 시스템 설정 변경 |

### 7-2. 정책 적용

```yaml
# config/mcp-servers.yaml 내 서버별 설정
servers:
  filesystem:
    trust_level: "read_only"
    allowed_paths: ["/Users/user/Documents", "/Users/user/Downloads"]
    denied_paths: ["/Users/user/.ssh", "/Users/user/.env*"]

  macos-control:
    trust_level: "system"
    approval_required: true
    allowed_actions: ["notes_create", "reminder_create", "volume_set"]
```

### 7-3. 감사 로그

모든 MCP 도구 호출은 `task_runs` 테이블에 기록한다.

```python
# 호출 시
TaskRun(
    task_type=f"mcp/{server_id}/{tool_name}",
    status="running",
    detail=json.dumps({"arguments": arguments}),
)
# 완료 시
TaskRun.status = "completed"
TaskRun.detail = json.dumps({"result": result})
```

---

## 8. 스킬 확장 시나리오

### 8-1. 새 내부 스킬 추가 (예: Reminder 관리)

```text
1. app/skills/reminder/ 디렉터리 생성
2. descriptor.py 에 SkillDescriptor 작성
3. extractor.py 에 파라미터 추출 로직 작성
4. executor.py 에 AppleScript 실행 로직 작성
5. registry.py 에 SKILL_REGISTRY 목록에 추가
→ 서버 재시작 시 자동으로 의도 분류 후보에 포함
```

### 8-2. 새 MCP 서버 연결 (예: Notion)

```text
1. config/mcp-servers.yaml 에 서버 설정 추가
2. 해당 MCP 서버가 노출하는 tools 목록을 자동 탐색
3. 필요 시 SkillDescriptor 로 래핑해 레지스트리에 등록
→ 코드 수정 없이 설정 파일만으로 도구 확장
```

### 8-3. 기존 n8n 워크플로를 스킬로 이관

```text
현재: automation.py 에서 직접 n8n webhook URL 호출
이후: SkillDescriptor(executor_type="n8n", executor_ref=webhook_path)로 등록
→ 실행 로직은 그대로, 메타데이터만 레지스트리로 이동
→ 의도 분류가 레지스트리 기반으로 자동화
```

---

## 9. 현재 작업과의 연결

이 설계는 기존 `implementation-plan.md`의 로드맵과 다음처럼 연결된다.

| implementation-plan 항목 | 이 문서의 Phase |
|--------------------------|----------------|
| 9번: LangGraph 기반 상태 라우팅 전환 | Phase 2 |
| 8번: AppleScript 추가 앱 확장 | Phase 4 (macOS MCP 서버) |
| 2번: LLM JSON extraction 전환 | Phase 1 (스킬별 extractor 분리) |
| 3번: 참조형 요청, 승인 후 재개 | Phase 2 (LangGraph interrupt/resume) |
| 7번: 브라우저 자동화 확장 | Phase 1 스킬 + Phase 3 MCP |

---

## 10. 기술 의존성

| 구성 요소 | 패키지/도구 | 버전 기준 |
|-----------|-------------|-----------|
| LangGraph | `langgraph` | 0.3+ |
| MCP 클라이언트 | `mcp` (Python SDK) | 1.0+ |
| MCP 서버 (커뮤니티) | `@modelcontextprotocol/server-*` | Node.js 기반 |
| 스킬 스키마 | `pydantic` | 2.10+ (기존 사용 중) |
| 작업 큐 | `redis` + 커스텀 또는 `arq` | 기존 Redis 활용 |

### 설치 시 추가될 pyproject.toml 변경

```toml
[project]
dependencies = [
    # 기존 의존성 유지
    "langgraph>=0.3",
    "mcp>=1.0",
]
```

---

## 11. 이 문서의 위치

- 이 문서는 `docs/plugin-and-skill-architecture.md` 에 위치한다.
- 구현 진행은 `docs/implementation-plan.md` 에 반영한다.
- 아키텍처 변경은 `docs/architecture.md` 에 동기화한다.
- 관련 코드 구조 변경은 `README.md` 에 반영한다.
