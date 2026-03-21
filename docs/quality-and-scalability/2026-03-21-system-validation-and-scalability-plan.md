# 시스템 검증 및 확장성 작업 방안 (2026-03-21)

## 문서 목적

- 현재 프로젝트의 기능 정상 동작 여부를 우선 확인한다.
- 실제 실패 지점을 근거 기반으로 분류한다.
- 단기 안정화와 중장기 확장성 개선을 동시에 추진할 수 있는 실행 계획을 제시한다.

## 이번 점검 범위

1. 자동 테스트 실행
- 대상: apps/api/tests, apps/api/app/tests
- 명령: /Volumes/ExtData/AI_Project/AI_Assistant/apps/api/.venv/bin/python -m pytest apps/api/tests apps/api/app/tests -q

2. 서비스 런타임 확인
- docker compose 상태 점검
- API 헬스 체크: GET /assistant/api/health
- Kakao webhook 스모크: POST /assistant/api/kakao/webhook

3. 앱별 기본 동작 스모크
- worker import 스모크
- browser-runner import 스모크

## 현재 결과 요약

### 1) 테스트 결과

- 총 140개 중 139개 통과, 1개 실패
- 실패 테스트:
  - ExternalLLMConfigTests.test_external_llm_disabled_by_default
- 직접 원인:
  - 테스트는 external_llm 기본 비활성(false)을 기대하지만, 실행 환경의 .env 에서는 EXTERNAL_LLM_ENABLED=true 로 설정되어 있음
- 해석:
  - 코드 기능 실패라기보다 테스트 격리 부족(환경 의존) 문제

### 2) 런타임 상태

- Docker 주요 서비스(api, worker, webui, proxy, postgres, redis, n8n) 정상 기동 확인
- GET /assistant/api/health 정상 응답 확인
- POST /assistant/api/kakao/webhook 정상 응답 확인
- worker, browser-runner import 스모크 통과

### 3) 운영 관점 위험

- 테스트가 로컬 운영 환경 변수(.env)에 직접 영향받음
- 테스트 실행 표준(의존성, fixture, profile)이 팀 공통으로 고정되어 있지 않음
- 기능 검증이 단위 테스트 중심이며, 채널/자동화/인프라를 포함한 회귀 E2E 세트가 부족함

## 구조적 문제 진단

### A. 설정 계층과 테스트 계층 결합

- 증상: 환경변수 1개(EXTERNAL_LLM_ENABLED)로 테스트 기대값이 변함
- 문제: 테스트가 "기본값"을 검증하면서 실제 런타임 설정을 그대로 읽고 있음
- 영향: 개발자/운영자 환경마다 테스트 결과가 달라질 수 있음

### B. 검증 파이프라인 표준 부재

- 증상: pytest 미설치 상태에서 테스트 시작이 실패
- 문제: dev/test 의존성과 실행 명령이 표준화되지 않음
- 영향: 검증 시작 비용 증가, CI 신뢰도 저하

### C. 기능 경계 분리는 진행 중이나 계약 테스트가 부족

- 현재 강점:
  - 도메인 스킬 분리, worker 큐 분리, MCP 확장 구조 반영
- 남은 과제:
  - API↔n8n, API↔browser-runner, API↔macOS runner 사이 계약(입출력 스키마) 회귀 테스트 부족

### D. 운영/개발 모드 분리가 더 필요

- 증상: 실제 운영 설정으로 테스트를 실행하게 됨
- 문제: local-dev, test, production 프로파일의 분리 수준이 부족
- 영향: 운영 안전성과 개발 생산성이 동시에 흔들릴 수 있음

## 확장성 개선 방안

## 1단계 (즉시, 1주)

1. 테스트 프로파일 고정
- .env.test 도입
- pytest 실행 시 test 전용 설정 강제 로드
- 기본값 테스트는 monkeypatch 또는 fixture로 환경변수 차단

2. 검증 명령 표준화
- 루트에 검증 스크립트 추가 (예: infra/scripts/validate-all.sh)
- 최소 검증 세트:
  - 단위 테스트
  - API health
  - 핵심 webhook 스모크

3. 의존성 표준화
- 앱별 dev dependency 명시(pytest 포함)
- 신규 환경에서도 즉시 테스트 가능한 상태 보장

## 2단계 (단기, 2~4주)

1. 계약 테스트 추가
- API↔n8n payload 계약 테스트
- API↔browser-runner 요청/응답 계약 테스트
- 승인 플로우(티켓 생성→승인→실행) 회귀 테스트

2. 관측성 강화
- 공통 request_id, task_id, session_id 로깅 강제
- 장애 분류(설정/네트워크/외부 API/검증 실패) 태그화

3. 테스트 계층 분리
- unit: 파서/라우팅/스키마
- integration: DB/Redis/API
- e2e-smoke: webhook + 자동화 경로 최소 세트

## 3단계 (중기, 1~2개월)

1. 확장형 모듈 경계 고도화
- 도메인별 패키지 경계 고정:
  - calendar, mail, browser, macos, memory
- 공통 인터페이스:
  - SkillExecutor, AutomationGateway, EventPublisher

2. 배포/운영 프로파일 정식화
- dev/test/prod 설정 로더 분리
- launchd/docker/mcp 실행 모드 별 안전 가드 추가

3. CI 파이프라인 구축
- PR 게이트:
  - unit + integration 필수 통과
  - e2e-smoke 선택/야간 배치

## 바로 실행할 작업 목록

1. 테스트 실패 1건 해소
- ExternalLLMConfigTests 를 환경 독립적으로 수정
- 기대값을 "기본 설정 객체"와 "런타임 설정 객체"로 분리 검증

2. test 전용 환경파일 도입
- .env.test 작성
- pytest 실행 시 강제 사용

3. 검증 스크립트 추가
- 한 번에 전체 상태를 점검하는 명령 집합 제공

4. 계약 테스트 우선순위 3개 추가
- calendar create
- gmail draft
- kakao webhook 기본 라우팅

## 성공 기준 (Done Definition)

- 어떤 개발자 환경에서도 동일 테스트 결과 재현
- 핵심 자동화 3개 이상 회귀 테스트 자동화
- 장애 발생 시 로그만으로 원인 분류 가능
- 신규 기능 추가 시 기존 핵심 흐름 회귀 실패를 5분 내 탐지

## 참고

- 구조 설계 문서: docs/plugin-and-skill-architecture.md
- 구현 진행 문서: docs/implementation-plan.md
- 운영 절차 문서: docs/service-operations.md
