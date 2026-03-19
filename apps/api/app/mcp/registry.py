"""MCP 도구 → SkillDescriptor 변환 및 스킬 레지스트리 등록."""

from __future__ import annotations

import logging

from mcp.types import Tool

from app.mcp.client import MCPManager
from app.skills.base import SkillDescriptor
from app.skills.registry import register_skill

logger = logging.getLogger("uvicorn.error")


def _tool_to_skill(server_name: str, tool: Tool, domain: str | None = None) -> SkillDescriptor:
    """MCP Tool을 SkillDescriptor로 변환한다."""
    tool_domain = domain or server_name
    return SkillDescriptor(
        skill_id=f"mcp_{server_name}_{tool.name}",
        name=tool.title or tool.name,
        description=tool.description or f"MCP tool: {tool.name}",
        domain=tool_domain,
        action=tool.name,
        trigger_keywords=_extract_keywords(tool),
        input_schema=dict(tool.inputSchema) if tool.inputSchema else None,
        output_schema=None,
        executor_type="mcp",
        executor_ref=f"{server_name}/{tool.name}",
        approval_required=False,
        risk_level="low",
        allowed_channels=["web", "kakao", "slack"],
        enabled=True,
    )


def _extract_keywords(tool: Tool) -> list[str]:
    """도구 이름과 설명에서 트리거 키워드를 추출한다."""
    keywords = [tool.name]
    if tool.title:
        keywords.append(tool.title)
    if tool.description:
        words = tool.description.split()
        keywords.extend(w.lower() for w in words[:5] if len(w) > 2)
    return keywords


def register_mcp_tools(manager: MCPManager) -> int:
    """MCPManager에서 발견된 모든 도구를 스킬 레지스트리에 등록한다."""
    registered = 0
    for server_name, tool in manager.get_all_tools():
        conn = manager._connections.get(server_name)
        domain = conn.config.domain if conn else None
        descriptor = _tool_to_skill(server_name, tool, domain)
        register_skill(descriptor)
        registered += 1
        logger.debug("Registered MCP skill: %s", descriptor.skill_id)

    logger.info("Registered %d MCP tools as skills", registered)
    return registered
