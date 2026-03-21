# 서비스 자동 시작 및 수동 운영 가이드

## 목적

이 문서는 macOS 호스트가 재부팅된 뒤 AI Assistant 핵심 서비스를 자동 시작하는 방법과, 운영자가 수동으로 시작, 중지, 상태 확인을 수행하는 방법을 정리한다.

현재 기준 자동 시작 대상은 아래와 같다.

- host MLX base server: `com.aiassistant.mlx-base-server`
- host MLX WebUI proxy: `com.aiassistant.mlx-webui-proxy`
- Docker Compose core stack: `com.aiassistant.stack`

24시간 무인 운영을 기준으로 보면 성격이 둘로 나뉜다.

- MLX base server와 MLX WebUI proxy는 LaunchDaemon으로 전환 가능하다.
- Docker Compose core stack은 현재 Docker Desktop을 사용하므로 로그인 세션 없는 완전한 LaunchDaemon 전환이 어렵다.

Docker Compose core stack에는 기본적으로 아래 서비스가 포함된다.

- `postgres`
- `redis`
- `n8n`
- `api`
- `worker`
- `webui`
- `proxy`

대용량 영속 데이터는 기본적으로 `/Volumes/ExtData/ai-assistant` 아래 bind mount 로 저장한다. 현재 기준으로 Open WebUI, n8n, PostgreSQL, Redis, Caddy, Guacamole 데이터와 MLX/Hugging Face 캐시를 이 경로 아래로 모은다.

## 관련 파일

- launchd 설치 스크립트: [infra/scripts/install-launchd-services.sh](infra/scripts/install-launchd-services.sh)
- core stack 시작 스크립트: [infra/scripts/start-assistant-stack.sh](infra/scripts/start-assistant-stack.sh)
- core stack 중지 스크립트: [infra/scripts/stop-assistant-stack.sh](infra/scripts/stop-assistant-stack.sh)
- 상태 확인 스크립트: [infra/scripts/status-assistant-services.sh](infra/scripts/status-assistant-services.sh)
- remote desktop 시작 스크립트: [infra/scripts/start-remote-desktop.sh](infra/scripts/start-remote-desktop.sh)
- remote desktop 중지 스크립트: [infra/scripts/stop-remote-desktop.sh](infra/scripts/stop-remote-desktop.sh)
- remote desktop 상태 스크립트: [infra/scripts/status-remote-desktop.sh](infra/scripts/status-remote-desktop.sh)
- Tailscale Serve 시작 스크립트: [infra/scripts/start-tailscale-serve.sh](infra/scripts/start-tailscale-serve.sh)
- Tailscale Serve 중지 스크립트: [infra/scripts/stop-tailscale-serve.sh](infra/scripts/stop-tailscale-serve.sh)
- Tailscale Serve 상태 스크립트: [infra/scripts/status-tailscale-serve.sh](infra/scripts/status-tailscale-serve.sh)
- LaunchDaemon 설치 스크립트: [infra/scripts/install-launchd-daemons.sh](infra/scripts/install-launchd-daemons.sh)
- 24시간 운영 상태 스크립트: [infra/scripts/status-24x7-readiness.sh](infra/scripts/status-24x7-readiness.sh)
- stack launchd plist: [infra/launchd/com.aiassistant.stack.plist](infra/launchd/com.aiassistant.stack.plist)
- MLX 운영 문서: [docs/mlx-operations.md](docs/mlx-operations.md)

## 자동 시작 설치

최초 1회는 아래 스크립트로 launchd agent를 설치한다.

```bash
infra/scripts/install-launchd-services.sh
```

외부 SSD로 기존 데이터를 옮길 때는 설치 전에 아래 스크립트를 1회 실행한다.

```bash
infra/scripts/migrate-extdata-storage.sh
```

이 스크립트는 아래 작업을 수행한다.

- `~/Library/LaunchAgents` 에 plist 복사
- 현재 저장소 절대 경로와 사용자 홈 경로로 plist 내부 값을 재작성
- 기존 동일 label이 있으면 `bootout`
- `bootstrap` 으로 재등록
- `kickstart` 로 즉시 시작

저장소 디렉토리를 이동한 경우에는 위 설치 스크립트를 다시 실행해 launchd 등록값을 갱신한다.

설치 후 확인 명령:

```bash
launchctl list | grep com.aiassistant.mlx-
launchctl list | grep com.aiassistant.stack
```

## LaunchDaemon 전환

MLX 계열 서비스를 로그인 없이 부팅 시점부터 올리려면 아래 스크립트를 사용한다.

```bash
sudo infra/scripts/install-launchd-daemons.sh
```

이 스크립트는 아래 작업을 수행한다.

- `com.aiassistant.mlx-base-server.daemon`
- `com.aiassistant.mlx-webui-proxy.daemon`
- 두 daemon plist를 `/Library/LaunchDaemons` 에 복사
- 현재 저장소 절대 경로, 실행 사용자, 홈 경로로 plist 내부 값을 재작성
- 기존 사용자 LaunchAgent 기반 MLX job을 disable + bootout 처리해 자동 로그인 이후에도 중복 실행 방지
- system domain에 bootstrap 후 즉시 kickstart

중요한 제한:

- 현재 `com.aiassistant.stack` 는 Docker Desktop에 의존하므로 LaunchDaemon으로 옮기지 않는다.
- 완전 무인 부팅 후 Docker stack까지 자동 복구하려면 다음 중 하나가 필요하다.
	- macOS 자동 로그인 유지
	- Docker Desktop 대신 headless Docker Engine 계열 런타임 사용

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

### 1-1. MLX LaunchDaemon 경로 수동 재적용

```bash
sudo infra/scripts/install-launchd-daemons.sh
```

### 2. Docker Compose core stack만 수동 시작

```bash
infra/scripts/start-assistant-stack.sh
```

이 스크립트는 `/Volumes/ExtData/ai-assistant` 아래 필요한 bind mount 디렉토리를 자동으로 생성한다.

특정 서비스만 시작할 수도 있다.

```bash
infra/scripts/start-assistant-stack.sh api worker
```

### 3. Guacamole remote desktop만 수동 시작

```bash
infra/scripts/start-remote-desktop.sh
```

이 스크립트는 현재 셸에 남아 있는 `GUACAMOLE_*` 환경변수를 비운 뒤 `.env` 기준으로 `remote-desktop` 프로필만 올린다.

### 4. Tailscale Serve HTTPS 시작

```bash
infra/scripts/start-tailscale-serve.sh
```

이 스크립트는 tailnet 내부에서 `https://<tailscale-host>/` 로 호스트 `80` 포트를 HTTPS 프록시한다.

### 5. MLX launchd만 수동 재시작

```bash
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-base-server
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-webui-proxy
```

LaunchDaemon 경로를 쓰는 경우:

```bash
sudo launchctl kickstart -k system/com.aiassistant.mlx-base-server.daemon
sudo launchctl kickstart -k system/com.aiassistant.mlx-webui-proxy.daemon
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

### 3. Tailscale Serve HTTPS 중지

```bash
infra/scripts/stop-tailscale-serve.sh
```

### 4. launchd job 해제

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
infra/scripts/status-tailscale-serve.sh
infra/scripts/status-24x7-readiness.sh
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
- 반대로 `com.aiassistant.mlx-base-server.daemon`, `com.aiassistant.mlx-webui-proxy.daemon` 는 로그인 없이도 부팅 시점부터 시작되도록 구성할 수 있다.
- Docker Desktop 자체의 로그인 자동 실행을 켜 두면 compose stack 시작 시간이 더 짧아진다.
- edge profile인 `cloudflared` 와 automation profile인 `browser-runner` 는 기본 자동 시작 대상에서 제외했다.
- Tailscale Serve는 Docker Compose가 아니라 host Tailscale 설정이므로 별도 스크립트로 관리한다.
- 필요 시 `AI_ASSISTANT_ENABLE_EDGE_PROFILE=true` 또는 `AI_ASSISTANT_ENABLE_AUTOMATION_PROFILE=true` 를 stack launchd plist 환경변수에 추가해 자동 시작 범위를 넓힐 수 있다.

## 24시간 운영 체크리스트

1. 전원 어댑터 연결 상태에서 `sleep=0`, `disksleep=0`, `autorestart=1` 기준으로 조정한다.
2. 디스플레이만 끄고 본체 잠자기는 끄는 방식으로 운영한다.
3. Docker Desktop 자동 실행을 켠다.
4. MLX 계열은 `sudo infra/scripts/install-launchd-daemons.sh` 로 LaunchDaemon 전환을 적용한다.
5. Tailscale 로그인 상태와 `infra/scripts/status-tailscale-serve.sh` 결과를 확인한다.
6. `infra/scripts/start-tailscale-serve.sh` 로 tailnet HTTPS를 활성화한다.
7. `infra/scripts/status-24x7-readiness.sh` 로 전원, Tailscale, MLX, Docker 상태를 한 번에 확인한다.
8. 정전 복구를 대비해 가능하면 UPS를 사용한다.
9. 재부팅 1회 테스트로 MLX daemon, Docker stack, Tailscale Serve 복구 순서를 실제 검증한다.
10. 완전 무인 운영이 필요하면 Docker Desktop 의존을 줄이거나 macOS 자동 로그인을 유지한다.