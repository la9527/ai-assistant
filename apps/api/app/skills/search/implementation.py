"""search 도메인 실행 가능한 skill 구현체."""

from __future__ import annotations

from pydantic import BaseModel

from app.skills.base import BaseSkill
from app.skills.search.descriptor import WEB_SEARCH_SKILL


class WebSearchSkill(BaseSkill):
    def descriptor(self):
        return WEB_SEARCH_SKILL

    async def extract(self, message: str, context: dict) -> BaseModel | None:
        return context.get("structured_extraction")

    async def validate(self, params: BaseModel) -> list[str]:
        return []

    async def execute(self, params: BaseModel, context: dict) -> dict:
        from app.llm import generate_local_reply
        from app.search import format_search_results_for_llm, run_web_search

        message = context["message"]
        channel = context["channel"]
        memory_context = context.get("memory_context")

        search_result = run_web_search(message)
        if search_result.get("error"):
            reply, route = generate_local_reply(message, channel, memory_context)
            return {"reply": reply, "route": route, "action_type": None}

        context_text = format_search_results_for_llm(search_result)
        search_memory = [{"category": "search_context", "content": context_text, "source": "web_search"}]
        combined_memory = (memory_context or []) + search_memory
        reply, route = generate_local_reply(
            f"다음 검색 결과를 바탕으로 사용자 질문에 답변해줘.\n\n{context_text}\n\n사용자 질문: {message}",
            channel,
            combined_memory,
        )
        return {"reply": reply, "route": "web_search", "action_type": "web_search"}


SKILL_IMPLEMENTATIONS = [WebSearchSkill()]