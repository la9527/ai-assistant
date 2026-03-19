"""웹 검색 모듈 — Tavily API 기반 인터넷 검색 및 결과 요약."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("uvicorn.error")


def run_web_search(query: str, max_results: int | None = None) -> dict:
    """Tavily API로 웹 검색을 실행하고 결과를 반환한다.

    Returns:
        {"results": [...], "query": str, "answer": str | None}
    """
    if not settings.web_search_available:
        return {"results": [], "query": query, "answer": None, "error": "웹 검색이 비활성화되어 있습니다."}

    max_results = max_results or settings.web_search_max_results

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            include_answer=True,
            search_depth="basic",
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            })
        return {
            "results": results,
            "query": query,
            "answer": response.get("answer"),
        }
    except ImportError:
        logger.warning("tavily-python not installed, web search unavailable")
        return {"results": [], "query": query, "answer": None, "error": "tavily-python 미설치"}
    except Exception as exc:
        logger.warning("Web search failed: %s", exc)
        return {"results": [], "query": query, "answer": None, "error": str(exc)}


def format_search_results_for_llm(search_result: dict) -> str:
    """검색 결과를 LLM 요약에 적합한 텍스트로 변환한다."""
    parts = [f"검색어: {search_result['query']}"]

    if search_result.get("answer"):
        parts.append(f"\n요약: {search_result['answer']}")

    for i, r in enumerate(search_result.get("results", []), 1):
        parts.append(f"\n[{i}] {r['title']}")
        parts.append(f"    URL: {r['url']}")
        content = r.get("content", "")
        if content:
            parts.append(f"    {content[:300]}")

    return "\n".join(parts)
