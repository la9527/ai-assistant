# Open WebUI 응답 포맷 가이드

작성일: 2026-03-21

## 목적

- Open WebUI에서 Gmail 요약, 상세, 후보 선택형 응답이 안정적으로 렌더링되도록 포맷 규칙을 고정한다.
- n8n workflow의 원본 문자열 형식과 WebUI 표시 형식을 분리해, UI 문제를 API 레벨에서 흡수한다.

## 적용 대상

- `apps/api/app/llm.py`
- `apps/api/app/automation.py`
- `apps/api/app/graph/nodes.py`

## WebUI-safe 포맷 규칙

- 메일 목록 번호는 `1.` 대신 `1)` 형식을 사용한다.
- 항목 본문에 `- ` 로 시작하는 Markdown list 문법을 사용하지 않는다.
- 메일 제목이나 상태 라벨의 `[조치 필요]` 같은 표기는 `(조치 필요)`처럼 괄호로 정규화한다.
- `\[ ... \]` 형태의 이스케이프는 사용하지 않는다.
  Open WebUI 렌더러가 KaTeX 수식으로 오해할 수 있다.
- WebUI 채널에서는 deterministic formatter를 우선 사용한다.
  외부 LLM 기반 재포맷은 출력 구조가 흔들릴 수 있으므로 WebUI 기본 경로에서는 사용하지 않는다.

## Gmail 요약 출력 원칙

- 시작 줄은 `📬 최근 메일 요약` 의미를 유지한다.
- 각 메일은 아래 구조를 따른다.

```text
1) 제목
보낸 사람: sender@example.com
날짜: 2026-03-21
미리보기: ...
```

- 제목은 굵게 처리할 수 있지만, 제목 아래 세부 정보는 일반 줄로 유지한다.

## Gmail 상세 출력 원칙

- 시작 줄은 `📩 메일 상세 정보` 의미를 유지한다.
- 메타데이터는 일반 줄로 유지한다.
- 본문은 `본문` 라벨 아래 별도 문단으로 둔다.

```text
제목: ...
보낸 사람: ...
받는 사람: ...
메시지 ID: ...
스레드 ID: ...

본문
...
```

## 구현 원칙

- n8n workflow 샘플 JSON은 원본 자동화 흐름의 예시로 유지한다.
- Open WebUI 렌더링 안정성은 FastAPI formatter 계층에서 보정한다.
- Gmail summary/detail의 legacy 경로와 LangGraph 경로는 동일 formatter를 사용한다.

## 검증 체크리스트

- Open WebUI에서 번호가 다음 항목과 합쳐지지 않는지 확인한다.
- `조치 필요`, `Action needed`, `Failure` 같은 텍스트가 KaTeX처럼 깨지지 않는지 확인한다.
- 메일 상세 응답에서 `- 제목:` 같은 list 스타일이 남지 않는지 확인한다.
- 후속 참조 대화에서 후보 추출이 유지되는지 확인한다.