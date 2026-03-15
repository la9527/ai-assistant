#!/usr/bin/env python3

from __future__ import annotations

import http.client
import json
import os
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse


UPSTREAM_BASE_URL = os.environ.get("MLX_WEBUI_PROXY_UPSTREAM", "http://127.0.0.1:1235").rstrip("/")
PROXY_HOST = os.environ.get("MLX_WEBUI_PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.environ.get("MLX_WEBUI_PROXY_PORT", "1236"))
ALLOWED_MODEL = os.environ.get("MLX_WEBUI_PROXY_MODEL", "lmstudio-community/LFM2-24B-A2B-MLX-4bit")


def _upstream_parts() -> tuple[str, int, str]:
    parsed = urlparse(UPSTREAM_BASE_URL)
    scheme = parsed.scheme or "http"
    if scheme != "http":
        raise RuntimeError("Only http upstreams are supported")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    base_path = parsed.path.rstrip("/")
    return host, port, base_path


class MLXWebUIProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/v1/models":
            self._handle_models()
            return
        self._proxy_request()

    def do_POST(self) -> None:
        self._proxy_request()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _handle_models(self) -> None:
        payload = {
            "object": "list",
            "data": [
                {
                    "id": ALLOWED_MODEL,
                    "object": "model",
                    "created": 0,
                    "owned_by": "openai",
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_request(self) -> None:
        host, port, base_path = _upstream_parts()
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        request_body = self.rfile.read(content_length) if content_length else None
        upstream_path = f"{base_path}{self.path}"

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }

        connection = http.client.HTTPConnection(host, port, timeout=300)
        try:
            connection.request(self.command, upstream_path, body=request_body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        except Exception as exc:
            error_body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)
            return
        finally:
            connection.close()

        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() in {"transfer-encoding", "connection", "keep-alive", "content-length"}:
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if response_body:
            self.wfile.write(response_body)


def main() -> None:
    server = ThreadingHTTPServer((PROXY_HOST, PROXY_PORT), MLXWebUIProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()