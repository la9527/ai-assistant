# 서비스 자동 시작 및 수동 운영 가이드

## 목적

이 문서는 macOS 호스트가 재부팅된 뒤 AI Assistant 핵심 서비스를 자동 시작하는 방법과, 운영자가 수동으로 시작, 중지, 상태 확인을 수행하는 방법을 정리한다.

현재 기준 자동 시작 대상은 아래와 같다.

- host llama.cpp LFM2 server: `com.aiassistant.llama-lfm2-server`
- Docker Compose core stack: `com.aiassistant.stack`

24시간 무인 운영을 기준으로 보면 성격이 둘로 나뉜다.

- llama.cpp LFM2 server는 LaunchDaemon으로 전환 가능하다.
- Docker Compose core stack은 현재 Docker Desktop을 사용하므로 로그인 세션 없는 완전한 LaunchDaemon 전환이 어렵다.

Docker Compose core stack에는 기본적으로 아래 서비스가 포함된다.

- `postgres`
- `redis`
- `n8n`
- `api`
- `worker`
- `webui`
- `proxy`

대용량 영속 데이터는 기본적으로 `/Volumes/ExtData/ai-assistant` 아래 bind mount 로 저장한다. 현재 기준으로 Open WebUI, n8n, PostgreSQL, Redis, Caddy, Guacamole 데이터와 llama.cpp/Hugging Face 캐시를 이 경로 아래로 모은다.

현재 운영 기준 n8n의 메타데이터 DB는 PostgreSQL을 사용한다. `/Volumes/ExtData/ai-assistant/docker/n8n` 는 n8n 설정 파일, event log, custom nodes, storage 디렉터리 같은 파일성 상태를 저장하고, 실제 workflow/credential/execution 메타데이터 DB는 `/Volumes/ExtData/ai-assistant/docker/postgres` 아래 PostgreSQL 데이터 안에 들어간다.

## 관련 파일

- launchd 설치 스크립트: [infra/scripts/install-launchd-services.sh](infra/scripts/install-launchd-services.sh)
- launchd daemon 설치 스크립트: [infra/scripts/install-launchd-daemons.sh](infra/scripts/install-launchd-daemons.sh)
- llama.cpp 시작 스크립트: [infra/scripts/start-llama-cpp-lfm2-server.sh](infra/scripts/start-llama-cpp-lfm2-server.sh)
- llama.cpp service 스크립트: [infra/scripts/start-llama-services.sh](infra/scripts/start-llama-services.sh), [infra/scripts/status-llama-services.sh](infra/scripts/status-llama-services.sh), [infra/scripts/stop-llama-services.sh](infra/scripts/stop-llama-services.sh), [infra/scripts/uninstall-llama-services.sh](infra/scripts/uninstall-llama-services.sh)
- core stack 시작 스크립트: [infra/scripts/start-assistant-stack.sh](infra/scripts/start-assistant-stack.sh)
- core stack 중지 스크립트: [infra/scripts/stop-assistant-stack.sh](infra/scripts/stop-assistant-stack.sh)
- 상태 확인 스크립트: [infra/scripts/status-assistant-services.sh](infra/scripts/status-assistant-services.sh)
- 24시간 운영 상태 스크립트: [infra/scripts/status-24x7-readiness.sh](infra/scripts/status-24x7-readiness.sh)
- stack launchd plist: [infra/launchd/com.aiassistant.stack.plist](infra/launchd/com.aiassistant.stack.plist)
- llama.cpp launchd plist: [infra/launchd/com.aiassistant.llama-lfm2-server.plist](infra/launchd/com.aiassistant.llama-lfm2-server.plist)
- llama.cpp 운영 문서: [docs/llama-cpp-operations.md](docs/llama-cpp-operations.md)

## 자동 시작 설치

최초 1회는 아래 스크립트로 LaunchAgent를 설치한다.

```bash
infra/scripts/install-launchd-services.sh
```

이 스크립트는 아래 작업을 수행한다.

- `~/Library/LaunchAgents` 에 plist 복사
- 현재 저장소 절대 경로와 사용자 홈 경로로 plist 내부 값을 재작성
- 기존 동일 label 이 있으면 `bootout`
- `bootstrap` 으로 재등록
- `kickstart` 로 즉시 시작
- system LaunchDaemon 이 이미 있으면 user LaunchAgent 는 건너뜀

저장소 디렉토리를 이동한 경우에는 위 설치 스크립트를 다시 실행해 launchd 등록값을 갱신한다.

설치 후 확인 명령:

```bash
launchctl list | grep com.aiassistant.llama-
launchctl list | grep com.aiassistant.stack
```

## LaunchDaemon 전환

llama.cpp 서비스를 로그인 없이 부팅 시점부터 올리려면 아래 스크립트를 사용한다.

```bash
sudo infra/scripts/install-launchd-daemons.sh
```

이 스크립트는 아래 작업을 수행한다.

- `com.aiassistant.llama-lfm2-server.daemon` 을 `/Library/LaunchDaemons` 에 복사
- 현재 저장소 절대 경로, 실행 사용자, 홈 경로로 plist 내부 값을 재작성
- 기존 사용자 LaunchAgent 기반 llama job 을 disable + bootout 처리해 자동 로그인 이후에도 중복 실행 방지
- system domain 에 bootstrap 후 즉시 kickstart

중요한 제한:

- 현재 `com.aiassistant.stack` 는 Docker Desktop 에 의존하므로 LaunchDaemon 으로 옮기지 않는다.
- 완전 무인 부팅 후 Docker stack 까지 자동 복구하려면 다음 중 하나가 필요하다.
- macOS 자동 로그인 유지
- Docker Desktop 대신 headless Docker Engine 계열 런타임 사용

## 재부팅 후 자동 시작 순서

로그인 세션이 열리면 launchd가 아래 순서를 사실상 병렬에 가깝게 시작한다.

1. `com.aiassistant.llama-lfm2-server`
2. `com.aiassistant.stack`

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

### 2. LaunchDaemon 경로 수동 재적용

```bash
sudo infra/scripts/install-launchd-daemons.sh
```

`assistant.sh` 래퍼를 쓰는 경우는 아래 명령으로 같다.

```bash
./assistant.sh launchd install
sudo ./assistant.sh launchd install-daemon
```

### 3. Docker Compose core stack만 수동 시작

```bash
infra/scripts/start-assistant-stack.sh
```

특정 서비스만 시작할 수도 있다.

```bash
infra/scripts/start-assistant-stack.sh api worker
```

### 4. llama.cpp launchd만 수동 재시작

```bash
infra/scripts/start-llama-services.sh
sudo infra/scripts/start-llama-services.sh
```

### 5. llama.cpp 상태 확인

```bash
infra/scripts/status-llama-services.sh
sudo infra/scripts/status-llama-services.sh
curl -sS http://127.0.0.1:1242/v1/models
```

### 6. llama.cpp 중지

```bash
infra/scripts/stop-llama-services.sh
sudo infra/scripts/stop-llama-services.sh
```

### 7. llama.cpp launchd 등록 제거

```bash
infra/scripts/uninstall-llama-services.sh
sudo infra/scripts/uninstall-llama-services.sh
```

## 원격 운영 관련

Guacamole remote desktop 및 Tailscale Serve 운영은 기존과 동일하다.

```bash
infra/scripts/start-remote-desktop.sh
infra/scripts/start-tailscale-serve.sh
```

## 운영 점검 명령

```bash
infra/scripts/status-assistant-services.sh
infra/scripts/status-24x7-readiness.sh
docker compose --env-file .env -f infra/docker/docker-compose.yml ps
curl -sS http://127.0.0.1:1242/v1/models
```
