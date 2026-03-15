# 서비스 자동 시작 및 수동 운영 가이드

## 목적

이 문서는 macOS 호스트가 재부팅된 뒤 AI Assistant 핵심 서비스를 자동 시작하는 방법과, 운영자가 수동으로 시작, 중지, 상태 확인을 수행하는 방법을 정리한다.

현재 기준 자동 시작 대상은 아래와 같다.

- host MLX base server: `com.aiassistant.mlx-base-server`
- host MLX WebUI proxy: `com.aiassistant.mlx-webui-proxy`
- Docker Compose core stack: `com.aiassistant.stack`

Docker Compose core stack에는 기본적으로 아래 서비스가 포함된다.

- `postgres`
- `redis`
- `n8n`
- `api`
- `worker`
- `webui`
- `proxy`

## 관련 파일

- launchd 설치 스크립트: [infra/scripts/install-launchd-services.sh](infra/scripts/install-launchd-services.sh)
- core stack 시작 스크립트: [infra/scripts/start-assistant-stack.sh](infra/scripts/start-assistant-stack.sh)
- core stack 중지 스크립트: [infra/scripts/stop-assistant-stack.sh](infra/scripts/stop-assistant-stack.sh)
- 상태 확인 스크립트: [infra/scripts/status-assistant-services.sh](infra/scripts/status-assistant-services.sh)
- remote desktop 시작 스크립트: [infra/scripts/start-remote-desktop.sh](infra/scripts/start-remote-desktop.sh)
- remote desktop 중지 스크립트: [infra/scripts/stop-remote-desktop.sh](infra/scripts/stop-remote-desktop.sh)
- remote desktop 상태 스크립트: [infra/scripts/status-remote-desktop.sh](infra/scripts/status-remote-desktop.sh)
- stack launchd plist: [infra/launchd/com.aiassistant.stack.plist](infra/launchd/com.aiassistant.stack.plist)
- MLX 운영 문서: [docs/mlx-operations.md](docs/mlx-operations.md)

## 자동 시작 설치

최초 1회는 아래 스크립트로 launchd agent를 설치한다.

```bash
infra/scripts/install-launchd-services.sh
```

이 스크립트는 아래 작업을 수행한다.

- `~/Library/LaunchAgents` 에 plist 복사
- 기존 동일 label이 있으면 `bootout`
- `bootstrap` 으로 재등록
- `kickstart` 로 즉시 시작

설치 후 확인 명령:

```bash
launchctl list | grep com.aiassistant.mlx-
launchctl list | grep com.aiassistant.stack
```

## 재부팅 후 자동 시작 순서

로그인 세션이 열리면 launchd가 아래 순서를 사실상 병렬에 가깝게 시작한다.

1. `com.aiassistant.mlx-base-server`
2. `com.aiassistant.mlx-webui-proxy`
3. `com.aiassistant.stack`

`com.aiassistant.stack` 는 내부적으로 아래 순서로 동작한다.

1. Docker Desktop이 이미 준비되었는지 확인
2. 준비되지 않았으면 `open -a Docker` 로 실행
3. `docker info` 성공까지 대기
4. `docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --build ...` 실행

## 수동 시작 방법

### 1. launchd 포함 전체 자동 시작 경로를 수동 재적용

```bash
infra/scripts/install-launchd-services.sh
```

### 2. Docker Compose core stack만 수동 시작

```bash
infra/scripts/start-assistant-stack.sh
```

특정 서비스만 시작할 수도 있다.

```bash
infra/scripts/start-assistant-stack.sh api worker
```

### 3. Guacamole remote desktop만 수동 시작

```bash
infra/scripts/start-remote-desktop.sh
```

이 스크립트는 현재 셸에 남아 있는 `GUACAMOLE_*` 환경변수를 비운 뒤 `.env` 기준으로 `remote-desktop` 프로필만 올린다.

### 4. MLX launchd만 수동 재시작

```bash
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-base-server
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-webui-proxy
```

## 수동 중지 방법

### 1. Docker Compose core stack 중지

```bash
infra/scripts/stop-assistant-stack.sh
```

특정 서비스만 중지할 수도 있다.

```bash
infra/scripts/stop-assistant-stack.sh api worker
```

### 2. Guacamole remote desktop 중지

```bash
infra/scripts/stop-remote-desktop.sh
```

### 3. launchd job 해제

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.stack.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-base-server.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-webui-proxy.plist
```

## 상태 확인

빠른 운영 확인:

```bash
infra/scripts/status-assistant-services.sh
infra/scripts/status-remote-desktop.sh
```

수동 확인:

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml ps
curl -sS http://127.0.0.1:1235/v1/models
curl -sS http://127.0.0.1:1236/v1/models
curl -sS http://127.0.0.1/assistant/api/health
```

## 로그 경로

- stack launchd 표준 로그: `/tmp/aiassistant-stack.log`
- stack launchd 오류 로그: `/tmp/aiassistant-stack.err.log`
- MLX base 표준 로그: `/tmp/aiassistant-mlx-base-server.log`
- MLX base 오류 로그: `/tmp/aiassistant-mlx-base-server.err.log`
- WebUI proxy 표준 로그: `/tmp/aiassistant-mlx-webui-proxy.log`
- WebUI proxy 오류 로그: `/tmp/aiassistant-mlx-webui-proxy.err.log`

예시:

```bash
tail -n 50 /tmp/aiassistant-stack.err.log
tail -n 50 /tmp/aiassistant-stack.log
```

## 운영 메모

- `com.aiassistant.stack` 는 로그인 세션 기준 LaunchAgent 이므로, macOS 부팅 직후 무인 상태가 아니라 사용자 로그인 이후에 실행된다.
- Docker Desktop 자체의 로그인 자동 실행을 켜 두면 compose stack 시작 시간이 더 짧아진다.
- edge profile인 `cloudflared` 와 automation profile인 `browser-runner` 는 기본 자동 시작 대상에서 제외했다.
- 필요 시 `AI_ASSISTANT_ENABLE_EDGE_PROFILE=true` 또는 `AI_ASSISTANT_ENABLE_AUTOMATION_PROFILE=true` 를 stack launchd plist 환경변수에 추가해 자동 시작 범위를 넓힐 수 있다.