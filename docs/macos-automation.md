# macOS AppleScript 자동화

이 문서는 macOS 호스트에서 실행하는 AppleScript 자동화 runner와 현재 연결된 승인 기반 Notes 메모 생성 시나리오를 설명한다.

## 현재 구현 범위

- FastAPI intent: `macos_note_create`
- 승인 전 응답: 승인 필요
- 승인 후 실행기: 호스트 프로세스 `worker.macos_runner`
- 현재 자동화 앱: Notes
- 현재 작업: 지정 폴더에 메모 생성

## 실행 구조

1. 사용자가 Web, Kakao, Slack 등 채널에서 메모 생성 요청을 보낸다.
2. FastAPI가 `macos_note_create` intent로 분류하고 approval ticket을 만든다.
3. 사용자가 `승인 <ticket_id>` 또는 승인 API를 호출한다.
4. FastAPI가 `MACOS_AUTOMATION_BASE_URL`의 host runner를 호출한다.
5. host runner가 `osascript`로 Notes 앱에 메모를 생성한다.

## host runner 실행

저장소 루트에서 아래 명령으로 macOS runner를 실행한다.

```bash
uv run --project apps/workers python -m worker.macos_runner
```

기본 포트는 `8091`이고, API 컨테이너는 기본값으로 `http://host.docker.internal:8091`를 사용한다.

## 환경 변수

- `MACOS_AUTOMATION_BASE_URL=http://host.docker.internal:8091`

필요 시 `.env`에 같은 값을 명시할 수 있다. 기본값이 있으므로 host runner가 같은 포트에서 뜬다면 필수는 아니다.

## 현재 요청 형식

현재는 안전한 파싱을 위해 제목과 내용 라벨을 명시하는 형식을 권장한다.

예시:

```text
메모에 제목 주간 점검 내용 Slack 도메인 준비와 browser runner 상태 확인 저장해줘
```

선택적으로 폴더를 지정할 수 있다.

```text
메모에 제목 운영 TODO 내용 API 재기동 점검 폴더 AI Assistant Ops 저장해줘
```

## 검증 순서

1. host macOS에서 runner를 실행한다.
2. API 컨테이너를 재빌드 또는 재기동한다.
3. 채팅 API로 메모 생성 요청을 보낸다.
4. approval ticket을 승인한다.
5. Notes 앱에 메모가 생성됐는지 확인한다.

## 권한 주의사항

- 첫 실행 시 터미널 또는 Python이 Notes 제어 권한을 요청할 수 있다.
- macOS 개인정보 보호 설정에서 자동화 권한이 차단돼 있으면 AppleScript가 실패한다.
- 컨테이너 내부에서는 macOS 앱 제어가 불가능하므로 runner는 반드시 호스트에서 실행해야 한다.

## 다음 확장 후보

- Reminder 생성
- Finder 파일 정리
- Safari 읽기 목록 또는 탭 기반 read-only 수집
- Notes 업데이트 또는 검색 시나리오