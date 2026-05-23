# llama.cpp 운영 가이드

## 목적

이 문서는 host macOS에서 llama.cpp LFM2 런타임을 운영할 때 필요한 확인 절차와 장애 대응 절차를 정리한다.

현재 기준 운영 구성은 아래와 같다.

- 일반 답변 모델: `LiquidAI/LFM2-24B-A2B-GGUF:Q4_0`
- 구조화 추출 모델: `LiquidAI/LFM2-24B-A2B-GGUF:Q4_0`
- base chat endpoint: `http://127.0.0.1:1242/v1`
- structured extraction endpoint: `http://127.0.0.1:1242/v1`
- API 컨테이너 접근 주소: `http://host.docker.internal:1242/v1`
- launchd label: `com.aiassistant.llama-lfm2-server`

모델 및 캐시 저장 기본 경로는 `/Volumes/ExtData/ai-assistant/llama-cpp` 로 둔다. `start-llama-cpp-lfm2-server.sh` 는 기본적으로 Hugging Face cache 를 이 경로 아래로 맞춘다.

## 관련 파일

- launchd plist: [infra/launchd/com.aiassistant.llama-lfm2-server.plist](infra/launchd/com.aiassistant.llama-lfm2-server.plist)
- launchd daemon plist: [infra/launchd/com.aiassistant.llama-lfm2-server.daemon.plist](infra/launchd/com.aiassistant.llama-lfm2-server.daemon.plist)
- startup script: [infra/scripts/start-llama-cpp-lfm2-server.sh](infra/scripts/start-llama-cpp-lfm2-server.sh)
- service scripts: [infra/scripts/start-llama-services.sh](infra/scripts/start-llama-services.sh), [infra/scripts/status-llama-services.sh](infra/scripts/status-llama-services.sh), [infra/scripts/stop-llama-services.sh](infra/scripts/stop-llama-services.sh), [infra/scripts/uninstall-llama-services.sh](infra/scripts/uninstall-llama-services.sh)
- 서비스 자동 시작 문서: [docs/service-operations.md](docs/service-operations.md)

## 현재 환경변수 기준

- `LOCAL_LLM_BASE_URL=http://host.docker.internal:1242/v1`
- `LOCAL_LLM_MODEL=LiquidAI/LFM2-24B-A2B-GGUF:Q4_0`
- `LOCAL_LLM_TIMEOUT_SECONDS=90`
- `LOCAL_LLM_PREWARM_ENABLED=true`
- `LOCAL_LLM_STRUCTURED_EXTRACTION_BASE_URL=http://host.docker.internal:1242/v1`
- `LOCAL_LLM_STRUCTURED_EXTRACTION_MODEL=LiquidAI/LFM2-24B-A2B-GGUF:Q4_0`
- `AI_STORAGE_ROOT=/Volumes/ExtData/ai-assistant`
- `LLAMA_CPP_ROOT=/Volumes/ExtData/ai-assistant/llama-cpp`

## 기본 상태 확인

```bash
infra/scripts/status-llama-services.sh
curl -sS http://127.0.0.1:1242/v1/models
docker exec docker-api-1 sh -lc 'python - <<"PY"
import httpx
r = httpx.get("http://host.docker.internal:1242/v1/models", timeout=20.0)
print(r.status_code)
print(r.text)
PY'
```

## 로그 확인

- user launchd 표준 로그: `/tmp/aiassistant-llama-lfm2-server.log`
- user launchd 오류 로그: `/tmp/aiassistant-llama-lfm2-server.err.log`
- daemon 표준 로그: `/tmp/aiassistant-llama-lfm2-server-daemon.log`
- daemon 오류 로그: `/tmp/aiassistant-llama-lfm2-server-daemon.err.log`

## 재기동 절차

```bash
infra/scripts/start-llama-services.sh
infra/scripts/status-llama-services.sh
infra/scripts/stop-llama-services.sh
sudo infra/scripts/install-launchd-daemons.sh
sudo infra/scripts/start-llama-services.sh
```

## 운영 메모

- standalone `mlx_lm.server` 경로는 제거했다.
- 현재 기본 운영안은 `1242=LFM2 llama.cpp` 단일 endpoint 를 일반 응답과 구조화 추출에 함께 사용한다.
- OpenClaw agentic workload 기준으로는 standalone MLX 대비 llama.cpp 경로가 prefix cache 재사용 측면에서 더 유리했다.
- 외부 공개 포트로 직접 노출하지 않고, host loopback 과 `host.docker.internal` 경로만 사용한다.