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


def _validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="url must be a valid http or https address")


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()