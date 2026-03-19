from datetime import UTC
from datetime import datetime
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
import uvicorn


class BrowserReadRequest(BaseModel):
    url: str
    wait_selector: str | None = Field(default=None, alias="waitSelector")
    timeout_ms: int = Field(default=15000, alias="timeoutMs", ge=1000, le=60000)
    max_chars: int = Field(default=4000, alias="maxChars", ge=500, le=12000)


class BrowserReadResponse(BaseModel):
    url: str
    final_url: str = Field(alias="finalUrl")
    title: str
    description: str | None = None
    headings: list[str]
    content_excerpt: str = Field(alias="contentExcerpt")
    fetched_at: str = Field(alias="fetchedAt")


class BrowserScreenshotRequest(BaseModel):
    url: str
    timeout_ms: int = Field(default=15000, alias="timeoutMs", ge=1000, le=60000)
    full_page: bool = Field(default=False, alias="fullPage")
    viewport_width: int = Field(default=1280, alias="viewportWidth", ge=320, le=3840)
    viewport_height: int = Field(default=720, alias="viewportHeight", ge=240, le=2160)


class BrowserSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, alias="maxResults", ge=1, le=10)
    timeout_ms: int = Field(default=20000, alias="timeoutMs", ge=1000, le=60000)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class BrowserSearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    fetched_at: str = Field(alias="fetchedAt")


app = FastAPI(title="AI Assistant Browser Runner", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/browse/read", response_model=BrowserReadResponse)
async def browse_read(payload: BrowserReadRequest) -> BrowserReadResponse:
    _validate_url(payload.url)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(payload.url, wait_until="domcontentloaded", timeout=payload.timeout_ms)
            if payload.wait_selector:
                await page.wait_for_selector(payload.wait_selector, timeout=payload.timeout_ms)

            page_data = await page.evaluate(
                r"""
                () => {
                  const normalize = (text) => (text || '').replace(/\s+/g, ' ').trim();
                  const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
                    .map((element) => normalize(element.textContent))
                    .filter(Boolean)
                    .slice(0, 8);
                  const description = document.querySelector('meta[name="description"]')?.content || null;
                  const article = document.querySelector('main, article, [role="main"]');
                  const bodyText = normalize((article || document.body).innerText || '');
                  return {
                    title: normalize(document.title),
                    description: normalize(description),
                    headings,
                    bodyText,
                  };
                }
                """
            )
            final_url = page.url
            await browser.close()
    except PlaywrightTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"browser read timed out: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browser runner failed: {exc}") from exc

    title = str(page_data.get("title") or "")
    if not title:
        raise HTTPException(status_code=422, detail="page title is empty")

    excerpt = str(page_data.get("bodyText") or "")[: payload.max_chars]
    if not excerpt:
        raise HTTPException(status_code=422, detail="page content is empty")

    headings = [str(item) for item in page_data.get("headings") or []]
    description_value = page_data.get("description")

    return BrowserReadResponse(
        url=payload.url,
        finalUrl=final_url,
        title=title,
        description=str(description_value) if description_value else None,
        headings=headings,
        contentExcerpt=excerpt,
        fetchedAt=datetime.now(UTC).isoformat(),
    )


@app.post("/browse/screenshot")
async def browse_screenshot(payload: BrowserScreenshotRequest):
    """페이지 스크린샷을 PNG 바이트로 반환한다."""
    _validate_url(payload.url)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": payload.viewport_width, "height": payload.viewport_height},
            )
            await page.goto(payload.url, wait_until="networkidle", timeout=payload.timeout_ms)
            png_bytes = await page.screenshot(full_page=payload.full_page, type="png")
            title = await page.title()
            await browser.close()
    except PlaywrightTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"screenshot timed out: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"screenshot failed: {exc}") from exc

    import base64

    return {
        "url": payload.url,
        "title": title,
        "image_base64": base64.b64encode(png_bytes).decode(),
        "width": payload.viewport_width,
        "height": payload.viewport_height,
        "fetchedAt": datetime.now(UTC).isoformat(),
    }


@app.post("/browse/search", response_model=BrowserSearchResponse)
async def browse_search(payload: BrowserSearchRequest) -> BrowserSearchResponse:
    """Google 검색 결과를 Playwright로 가져온다."""
    import urllib.parse

    search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(payload.query)}&hl=ko"

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            await page.goto(search_url, wait_until="domcontentloaded", timeout=payload.timeout_ms)
            await page.wait_for_selector("#search", timeout=payload.timeout_ms)

            raw_results = await page.evaluate(
                r"""
                (maxResults) => {
                  const items = [];
                  document.querySelectorAll('#search .g').forEach((el) => {
                    if (items.length >= maxResults) return;
                    const anchor = el.querySelector('a[href]');
                    const title = el.querySelector('h3');
                    const snippet = el.querySelector('.VwiC3b, [data-sncf], [style*="-webkit-line-clamp"]');
                    if (anchor && title) {
                      items.push({
                        title: (title.textContent || '').trim(),
                        url: anchor.href,
                        snippet: (snippet?.textContent || '').trim(),
                      });
                    }
                  });
                  return items;
                }
                """,
                payload.max_results,
            )
            await browser.close()
    except PlaywrightTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"search timed out: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"search failed: {exc}") from exc

    results = [
        SearchResult(
            title=str(r.get("title", "")),
            url=str(r.get("url", "")),
            snippet=str(r.get("snippet", "")),
        )
        for r in (raw_results or [])
    ]

    return BrowserSearchResponse(
        query=payload.query,
        results=results,
        fetchedAt=datetime.now(UTC).isoformat(),
    )


def _validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="url must be a valid http or https address")


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()