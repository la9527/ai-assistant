# MLX 운영 가이드

## 목적

이 문서는 host macOS에서 MLX 런타임을 운영할 때 필요한 확인 절차와 장애 대응 절차를 정리한다.

현재 기준 운영 구성은 아래와 같다.

- 일반 답변 모델: MLX `lmstudio-community/LFM2-24B-A2B-MLX-4bit`
- 구조화 추출 모델: MLX `lmstudio-community/LFM2-24B-A2B-MLX-4bit`
- base chat endpoint: `http://127.0.0.1:1235/v1`
- Gemma 4 sidecar endpoint: `http://127.0.0.1:1240/v1`
- structured extraction endpoint: `http://127.0.0.1:1235/v1`
- API 컨테이너 접근 주소: base chat=`http://host.docker.internal:1235/v1`, structured extraction=`http://host.docker.internal:1235/v1`
- Open WebUI 연결 주소: `http://host.docker.internal:1236/v1` 를 WebUI 전용 filtered OpenAI-compatible connection으로 사용
- launchd label: base chat=`com.aiassistant.mlx-base-server`
- launchd label: Gemma sidecar=`com.aiassistant.mlx-gemma-server`
- WebUI proxy launchd label: `com.aiassistant.mlx-webui-proxy`

기본 launchd 운영에서는 `mlx-base-server + mlx-webui-proxy` 만 기본 실행 대상으로 보고, Gemma sidecar 는 필요할 때만 별도로 올린다.

모델 및 캐시 저장 기본 경로는 `/Volumes/ExtData/ai-assistant/mlx` 로 둔다. `start-mlx-base-server.sh` 는 기본적으로 `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE`, `LMSTUDIO_HOME` 을 이 경로 아래로 맞춘다.

## 관련 파일

- base launchd plist: [infra/launchd/com.aiassistant.mlx-base-server.plist](infra/launchd/com.aiassistant.mlx-base-server.plist)
- Gemma launchd plist: [infra/launchd/com.aiassistant.mlx-gemma-server.plist](infra/launchd/com.aiassistant.mlx-gemma-server.plist)
- base startup script: [infra/scripts/start-mlx-base-server.sh](infra/scripts/start-mlx-base-server.sh)
- WebUI proxy script: [infra/scripts/start-mlx-webui-proxy.sh](infra/scripts/start-mlx-webui-proxy.sh)
- WebUI proxy plist: [infra/launchd/com.aiassistant.mlx-webui-proxy.plist](infra/launchd/com.aiassistant.mlx-webui-proxy.plist)
- 서비스 자동 시작 문서: [docs/service-operations.md](docs/service-operations.md)
- API 설정: [apps/api/app/config.py](apps/api/app/config.py)
- extraction 호출 계층: [apps/api/app/llm.py](apps/api/app/llm.py)

## 현재 환경변수 기준

- `LOCAL_LLM_BASE_URL=http://host.docker.internal:1235/v1`
- `LOCAL_LLM_MODEL=lmstudio-community/LFM2-24B-A2B-MLX-4bit`
- `LOCAL_LLM_TIMEOUT_SECONDS=90`
- `LOCAL_LLM_PREWARM_ENABLED=true`
- `LOCAL_LLM_STRUCTURED_EXTRACTION_BASE_URL=http://host.docker.internal:1235/v1`
- `LOCAL_LLM_STRUCTURED_EXTRACTION_MODEL=lmstudio-community/LFM2-24B-A2B-MLX-4bit`
- `AI_STORAGE_ROOT=/Volumes/ExtData/ai-assistant`
- `MLX_CACHE_ROOT=/Volumes/ExtData/ai-assistant/mlx`
- Open WebUI compose env는 `ENABLE_OPENAI_API=true`, `OPENAI_API_BASE_URLS=http://host.docker.internal:1236/v1`, `ENABLE_OLLAMA_API=false` 기준으로 둔다.

## 기본 상태 확인

1. launchd 등록 상태 확인

```bash
infra/scripts/status-mlx-services.sh
infra/scripts/status-mlx-services.sh gemma
```

2. 모델 endpoint 확인

```bash
curl -sS http://127.0.0.1:1235/v1/models
curl -sS http://127.0.0.1:1240/v1/models
curl -sS http://127.0.0.1:1236/v1/models
```

3. API 컨테이너에서 MLX 접근 확인

```bash
docker exec docker-api-1 sh -lc 'python - <<"PY"
import httpx
r = httpx.get("http://host.docker.internal:1235/v1/models", timeout=20.0)
print(r.status_code)
print(r.text)
PY'
```

4. API health 확인

```bash
curl -sS https://ai-assistant-kakao.la9527.cloud/assistant/api/health
```

## 로그 확인

- base server 표준 로그: `/tmp/aiassistant-mlx-base-server.log`
- base server 오류 로그: `/tmp/aiassistant-mlx-base-server.err.log`
- Gemma sidecar 표준 로그: `/tmp/aiassistant-mlx-gemma-server.log`
- Gemma sidecar 오류 로그: `/tmp/aiassistant-mlx-gemma-server.err.log`
- WebUI proxy 표준 로그: `/tmp/aiassistant-mlx-webui-proxy.log`
- WebUI proxy 오류 로그: `/tmp/aiassistant-mlx-webui-proxy.err.log`

예시:

```bash
tail -n 50 /tmp/aiassistant-mlx-base-server.err.log
tail -n 50 /tmp/aiassistant-mlx-base-server.log
tail -n 50 /tmp/aiassistant-mlx-webui-proxy.err.log
```

## 재기동 절차

전체 서비스 자동 시작 설치와 수동 start/stop/status 절차는 [docs/service-operations.md](docs/service-operations.md) 기준으로 운영한다.

메모리 점유를 즉시 내리고 싶다면 아래 stop 스크립트를 먼저 사용한다.

```bash
infra/scripts/stop-mlx-services.sh
```

- 기본값은 `mlx-base-server + mlx-webui-proxy` 만 중지한다.
- Gemma만 따로 중지하려면 `infra/scripts/stop-mlx-services.sh gemma` 를 사용한다.
- 전체를 한 번에 내리려면 `infra/scripts/stop-mlx-services.sh all` 을 사용한다.
- 현재 로그인한 사용자 LaunchAgent만 중지한다.
- boot-time LaunchDaemon까지 같이 내리려면 아래처럼 실행한다.

상태만 확인하려면 아래처럼 사용한다.

```bash
infra/scripts/status-mlx-services.sh
infra/scripts/status-mlx-services.sh gemma
infra/scripts/status-mlx-services.sh all
```

부분 daemon 운영 상태에서는 label별 관리 주체가 다를 수 있다. 현재 검증 기준으로 `mlx-base-server` 는 system LaunchDaemon, `mlx-webui-proxy` 는 user LaunchAgent 조합도 정상 동작한다. 이 경우 non-sudo `start-mlx-services.sh` 는 daemon-backed label을 건너뛰고 user-managed label만 다시 올린다.

```bash
sudo infra/scripts/stop-mlx-services.sh
```

boot-time 자동 시작 자체를 제거하려면 아래 uninstall 스크립트를 사용한다.

```bash
infra/scripts/uninstall-mlx-services.sh
sudo infra/scripts/uninstall-mlx-services.sh
```

- 기본값은 `mlx-base-server + mlx-webui-proxy` 제거
- Gemma만 따로 제거하려면 `infra/scripts/uninstall-mlx-services.sh gemma`
- 전체를 한 번에 제거하려면 `infra/scripts/uninstall-mlx-services.sh all`
- 첫 줄은 사용자 LaunchAgent 제거
- 둘째 줄은 system LaunchDaemon 제거까지 포함

1. launchd job 재시작

```bash
cp infra/launchd/com.aiassistant.mlx-base-server.plist ~/Library/LaunchAgents/
cp infra/launchd/com.aiassistant.mlx-gemma-server.plist ~/Library/LaunchAgents/
cp infra/launchd/com.aiassistant.mlx-webui-proxy.plist ~/Library/LaunchAgents/
launchctl enable gui/$(id -u)/com.aiassistant.mlx-base-server
launchctl enable gui/$(id -u)/com.aiassistant.mlx-gemma-server
launchctl enable gui/$(id -u)/com.aiassistant.mlx-webui-proxy
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-base-server.plist >/dev/null 2>&1 || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-gemma-server.plist >/dev/null 2>&1 || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-webui-proxy.plist >/dev/null 2>&1 || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-base-server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-gemma-server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-webui-proxy.plist
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-base-server
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-webui-proxy
```

래퍼 명령으로는 아래처럼 사용할 수 있다.

```bash
./infra/scripts/assistant.sh launchd install
./infra/scripts/assistant.sh launchd install-gemma
sudo ./infra/scripts/assistant.sh launchd install-daemon
sudo ./infra/scripts/assistant.sh launchd install-daemon-gemma
```

Gemma sidecar 는 필요할 때만 별도로 올린다.

```bash
launchctl enable gui/$(id -u)/com.aiassistant.mlx-gemma-server
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aiassistant.mlx-gemma-server.plist
launchctl kickstart -k gui/$(id -u)/com.aiassistant.mlx-gemma-server
```

LaunchDaemon 전환 스크립트를 이미 적용한 상태라면, 위 `launchctl enable` 두 줄이 없으면 user LaunchAgent가 다시 올라오지 않는다.

2. API 설정 재반영

```bash
docker compose -f infra/docker/docker-compose.yml up -d --build api
```

3. 대용량 캐시/스토리지 이전 1회 수행

```bash
infra/scripts/migrate-extdata-storage.sh
```

## 운영 메모

- 구조화 추출은 별도 coder 모델 없이 같은 `LFM2-24B-A2B-MLX-4bit` 에 extraction prompt를 보내고, 실패 시 baseline parser로 fallback 하는 구성을 기준으로 운영한다.
- API startup 시 base chat endpoint로 짧은 prewarm 요청을 먼저 보내 cold start fallback 가능성을 줄인다.
- 첫 일반 chat timeout 은 `LOCAL_LLM_TIMEOUT_SECONDS` 로 조절한다. 현재 권장값은 90초다.
- 32GB 메모리 환경에서는 `LFM2` 와 `Qwen3-Coder` 를 동시에 상시 유지할 때 memory pressure와 swap 사용량이 커져 안정성이 떨어질 수 있다.
- 현재 기본 운영안은 `1235=LFM2`, `1240=Gemma 4 E4B 4bit`, `1236=WebUI filtered proxy` 세 서비스만 유지하고, `1234` 구조화 추출 전용 MLX 서버는 비활성 상태로 둔다.
- 다만 메모리 절약이 우선이면 기본 상시 운용은 `1235=LFM2`, `1236=WebUI filtered proxy` 로 두고, `1240=Gemma 4 E4B 4bit` 는 비교 평가 시점에만 올린다.

## Gemma 4 E4B 4bit sidecar

- Gemma sidecar 는 `mlx-community/gemma-4-e4b-it-4bit` 를 `1240` 에 별도 기동한다.
- LFM2 와 분리된 별도 provider/model 선택 항목으로 OpenClaw 에 등록해 비교 평가용으로 사용한다.
- 현재 plist 기본 튜닝값은 `temp=0.0`, `prompt-cache-size=8`, `prompt-cache-bytes=3221225472`, `prefill-step-size=4096` 이다.

## 기능 검증 명령

### Calendar create

```bash
curl -sS -X POST 'https://ai-assistant-kakao.la9527.cloud/assistant/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{"channel":"web","message":"내일 오후 3시에 치과 일정 추가해줘"}'
```

### Calendar update

```bash
curl -sS -X POST 'https://ai-assistant-kakao.la9527.cloud/assistant/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{"channel":"web","message":"내일 오후 4시 치과 일정 변경해줘"}'
```

### Calendar delete

```bash
curl -sS -X POST 'https://ai-assistant-kakao.la9527.cloud/assistant/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{"channel":"web","message":"오늘 06:00-07:00 피자 시키기 일정 삭제해줘"}'
```

### Gmail draft

```bash
curl -sS -X POST 'https://ai-assistant-kakao.la9527.cloud/assistant/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{"channel":"web","message":"test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 초안 작성해줘"}'
```

### Gmail send

```bash
curl -sS -X POST 'https://ai-assistant-kakao.la9527.cloud/assistant/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{"channel":"web","message":"test@example.com로 제목 주간 보고 내용 오늘 작업 완료 메일 보내줘"}'
```

## 현재 검증 완료 범위

- `calendar_create` 승인 후 실제 일정 생성 완료
- `calendar_update` 승인 후 실제 일정 변경 완료
- `calendar_delete` 승인 후 실제 일정 삭제 완료
- `gmail_draft` 승인 후 실제 Draft 생성 완료
- `gmail_send` 승인 후 실제 메일 발송 완료

## 주의사항

- `mlx_lm.server` 는 자체 경고처럼 production-grade 보안 기능이 제한적이므로 외부 공개 포트로 직접 노출하지 않는다.
- MLX extraction 결과는 baseline parser와 병합되므로, 저장된 metadata에 `merged_with_baseline=true` 가 나타나는 것이 정상이다.
- 모델 cold start 직후에는 응답이 느릴 수 있으므로 재시작 검증 시 최소 10초 정도의 여유를 두는 편이 안전하다.
- `stop-mlx-services.sh` 는 현재 프로세스를 내리지만 plist 파일은 유지한다. 재부팅 이후 자동 시작까지 막으려면 `uninstall-mlx-services.sh` 를 사용한다.