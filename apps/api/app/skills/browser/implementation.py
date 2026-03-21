"""browser 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel

from app.config import settings
from app.skills.base import BaseSkill
from app.skills.browser.descriptor import BROWSER_READ_SKILL
from app.skills.browser.descriptor import BROWSER_SCREENSHOT_SKILL
from app.skills.browser.descriptor import BROWSER_SEARCH_SKILL


def _extract_url(message: str) -> str | None:
    match = re.search(r"https?://[^\s,]+", message, re.IGNORECASE)
    if match is None:
        return None
    return match.group(0)


def _extract_search_query(message: str) -> str | None:
    normalized = re.sub(r"\s+", " ", message).strip()
    normalized = re.sub(r"^(구글에서|google에서|브라우저로)\s*", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*(검색해줘|검색해 줘|검색)$", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.strip(" ?")
    return normalized or None


class _BaseBrowserSkill(BaseSkill):
    descriptor_model = BROWSER_READ_SKILL

    def descriptor(self):
        return self.descriptor_model

    async def extract(self, message: str, context: dict) -> BaseModel | None:
        return context.get("structured_extraction")


class BrowserReadSkill(_BaseBrowserSkill):
    descriptor_model = BROWSER_READ_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        browser = getattr(params, "browser", None)
        if browser and browser.url:
            return []
        return [] if _extract_url(params.raw_message) else ["url"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        browser = getattr(params, "browser", None)
        url = browser.url if browser and browser.url else _extract_url(context["message"])
        request_body = {"url": url, "timeoutMs": 15000, "maxChars": 4000}
        try:
            with httpx.Client(timeout=25.0) as client:
                response = client.post(
                    f"{settings.browser_runner_base_url.rstrip('/')}/browse/read",
                    json=request_body,
                )
                response.raise_for_status()
            data = response.json()
        except Exception:
            return {
                "reply": "브라우저 읽기 실행에 실패했습니다. browser-runner 연결 상태를 확인하세요.",
                "route": "browser_fallback",
            }

        title = str(data.get("title") or url)
        excerpt = str(data.get("contentExcerpt") or "")
        reply = f"페이지를 읽었습니다.\n제목: {title}"
        if excerpt:
            reply += f"\n요약: {excerpt}"
        return {"reply": reply, "route": "browser", "browser_result": data}


class BrowserScreenshotSkill(_BaseBrowserSkill):
    descriptor_model = BROWSER_SCREENSHOT_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        browser = getattr(params, "browser", None)
        if browser and browser.url:
            return []
        return [] if _extract_url(params.raw_message) else ["url"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        browser = getattr(params, "browser", None)
        url = browser.url if browser and browser.url else _extract_url(context["message"])
        full_page = browser.full_page if browser and browser.full_page is not None else False
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{settings.browser_runner_base_url.rstrip('/')}/browse/screenshot",
                    json={"url": url, "timeoutMs": 15000, "fullPage": full_page},
                )
                response.raise_for_status()
            data = response.json()
        except Exception:
            return {
                "reply": "브라우저 스크린샷 실행에 실패했습니다. browser-runner 연결 상태를 확인하세요.",
                "route": "browser_fallback",
            }
        return {
            "reply": f"페이지 스크린샷을 캡처했습니다.\nURL: {url}",
            "route": "browser",
            "browser_result": data,
        }


class BrowserSearchSkill(_BaseBrowserSkill):
    descriptor_model = BROWSER_SEARCH_SKILL

    async def validate(self, params: BaseModel) -> list[str]:
        browser = getattr(params, "browser", None)
        if browser and browser.query:
            return []
        return [] if _extract_search_query(params.raw_message) else ["query"]

    async def execute(self, params: BaseModel, context: dict) -> dict:
        browser = getattr(params, "browser", None)
        query = browser.query if browser and browser.query else _extract_search_query(context["message"])
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{settings.browser_runner_base_url.rstrip('/')}/browse/search",
                    json={"query": query, "maxResults": 5, "timeoutMs": 20000},
                )
                response.raise_for_status()
            data = response.json()
        except Exception:
            return {
                "reply": "브라우저 검색 실행에 실패했습니다. browser-runner 연결 상태를 확인하세요.",
                "route": "browser_fallback",
            }

        items = data.get("items") or data.get("results") or []
        lines = [f"브라우저 검색을 완료했습니다.\n질의: {query}"]
        for index, item in enumerate(items[:5], start=1):
            title = str(item.get("title") or item.get("text") or "제목 없음")
            url = str(item.get("url") or item.get("link") or "")
            lines.append(f"{index}. {title}")
            if url:
                lines.append(url)
        return {"reply": "\n".join(lines), "route": "browser", "browser_result": data}


SKILL_IMPLEMENTATIONS = [
    BrowserReadSkill(),
    BrowserScreenshotSkill(),
    BrowserSearchSkill(),
]