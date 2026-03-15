# 외부 접근 토폴로지

현재 이 프로젝트의 외부 접근 기준은 아래와 같다.

```text
[외부 사용자 / Kakao]
  -> Cloudflare Tunnel
  -> Caddy proxy
  -> FastAPI /assistant/api/kakao/webhook

[본인 브라우저 / 노트북]
  -> Tailscale tailnet
  -> Open WebUI (/)
  -> n8n (:5678)
  -> SSH

[맥미니 내부]
  -> FastAPI
  -> n8n
  -> Open WebUI
  -> Ollama
  -> Redis / PostgreSQL
```

핵심 원칙은 공개 인터넷에는 Kakao webhook ingress만 두고, 운영자용 웹 UI와 SSH는 Tailscale로만 접근하는 것이다.

## 1. Cloudflare Tunnel 적용 범위

- 목적: Kakao 공식 채널 또는 OpenBuilder webhook 공개 경로 제공
- 공개 경로: `https://<kakao-host>/assistant/api/kakao/webhook`
- 내부 연결 대상: Docker 네트워크의 `proxy:80`
- 구성 위치: `infra/docker/docker-compose.yml` 의 `cloudflared` 서비스

현재 저장소에는 아래 선택 프로필이 추가되어 있다.

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml --profile edge up -d cloudflared
```

실행 전에 `.env`에 아래 값을 넣어야 한다.

```env
CLOUDFLARE_TUNNEL_TOKEN=<Cloudflare dashboard tunnel token>
KAKAO_PUBLIC_BASE_URL=https://kakao-assistant.example.com
```

## 2. Cloudflare Dashboard 설정 절차

1. Cloudflare Zero Trust에서 Tunnel을 생성한다.
2. Docker connector용 token을 발급한다.
3. Public Hostname을 1개 만든다.
4. Hostname은 Kakao용 도메인 예: `kakao-assistant.example.com` 으로 둔다.
5. Service type은 `HTTP`로 두고 대상은 `http://proxy:80`로 지정한다.
6. Kakao 관리자센터 또는 OpenBuilder webhook URL을 `https://<kakao-host>/assistant/api/kakao/webhook` 로 입력한다.

중요한 점은 Cloudflare Tunnel이 Caddy 앞단에 붙고, 실제 FastAPI 경로는 기존 프록시 규칙대로 `/assistant/api/*` 를 유지한다는 것이다.

## 3. Tailscale 적용 범위

- 목적: 본인 브라우저, 노트북, SSH, 운영자용 UI 접근
- 접근 대상:
  - Open WebUI: `http://<tailscale-host>/`
  - n8n: `http://<tailscale-host>:5678`
  - SSH: `ssh <mac-user>@<tailscale-host>`

이 경로는 공개 인터넷이 아니라 tailnet 내부 접근만 허용한다.

현재 확인된 실제 호스트명은 `byoungyoung-macmini.tail53bcc7.ts.net` 이고, 아래 경로가 로컬 검증에서 200 응답을 반환했다.

- `http://byoungyoung-macmini.tail53bcc7.ts.net/`
- `http://byoungyoung-macmini.tail53bcc7.ts.net:5678/`

## 4. Tailscale 적용 절차

맥미니 호스트에서 먼저 Tailscale을 설치하고 로그인한다.

```bash
tailscale status
```

현재 설치된 macOS GUI build에서는 `tailscale up --ssh` 가 지원되지 않았다. 따라서 SSH는 Tailscale 전용 SSH 서버가 아니라 macOS 기본 `Remote Login`을 켠 뒤 일반 SSH over Tailscale 방식으로 사용한다.

확인할 항목:

1. `tailscale status` 에서 맥미니가 tailnet에 등록됐는지 확인한다.
2. MagicDNS 호스트명 또는 tailnet IP를 확인한다.
3. 노트북이나 개인 기기에서도 같은 tailnet에 로그인한다.
4. 브라우저에서 `http://<tailscale-host>/` 와 `http://<tailscale-host>:5678` 접속을 확인한다.
5. macOS `시스템 설정 -> 일반 -> 공유 -> 원격 로그인`을 켠 뒤 일반 `ssh`로 접속을 확인한다.

## 5. 현재 운영 권장 명령

기본 앱 계층:

```bash
docker compose -f infra/docker/docker-compose.yml up -d proxy postgres redis api worker webui n8n
```

Kakao 공개 ingress까지 포함:

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml --profile edge up -d cloudflared
```

브라우저 자동화까지 포함:

```bash
docker compose -f infra/docker/docker-compose.yml --profile automation up -d browser-runner
```

## 6. 적용 후 점검 순서

1. `GET /assistant/api/health` 가 proxy 경유로 응답하는지 확인한다.
2. Kakao webhook 공개 URL이 Cloudflare Tunnel 뒤에서 200 또는 정상 webhook 응답을 주는지 확인한다.
3. Tailscale 기기에서 Open WebUI와 n8n 접속이 되는지 확인한다.
4. SSH가 tailnet 경로로 접속되는지 확인한다.

현재 검증 결과:

- `https://ai-assistant-kakao.la9527.cloud/assistant/api/health` 에서 `200 OK` 확인
- `https://ai-assistant-kakao.la9527.cloud/assistant/api/kakao/webhook` 에서 실제 Kakao 형식 응답 확인
- `http://byoungyoung-macmini.tail53bcc7.ts.net/` 에서 Open WebUI `200 OK` 확인
- `http://byoungyoung-macmini.tail53bcc7.ts.net:5678/` 에서 n8n `200 OK` 확인

SSH 점검은 별도로 macOS 원격 로그인이 켜져 있어야 한다. 현재 세션에서는 관리자 권한이 없어 이 설정을 직접 확인하지 못했다.

## 7. 주의사항

- Open WebUI, n8n, SSH는 공유기 포트포워딩으로 공개하지 않는다.
- Cloudflare Tunnel은 Kakao 공개 webhook 같은 좁은 공개 경로에만 사용한다.
- Slack 공개 webhook를 나중에 붙일 경우에도 같은 Tunnel을 재사용할 수 있지만 hostname 분리는 유지하는 편이 운영상 안전하다.
- Tailscale은 호스트 레벨 서비스이므로 Docker Compose만으로 인증과 로그인까지 자동화하지 않는다.
- macOS GUI build에서는 `tailscale up --ssh` 가 동작하지 않을 수 있으므로, SSH는 기본적으로 `Remote Login + ssh <user>@<tailscale-host>` 기준으로 운영한다.
- Cloudflare Tunnel token은 루트 `.env`에 있으므로 `cloudflared` 실행 시 `docker compose --env-file .env ...` 형태로 명시적으로 넘기는 편이 안전하다.

Kakao 채널과 OpenBuilder 설정 절차는 [docs/kakao-integration.md](docs/kakao-integration.md)에 따로 정리한다.