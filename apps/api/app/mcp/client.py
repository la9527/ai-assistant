"""MCP 클라이언트 매니저 — MCP 서버 연결, 도구 발견, 도구 호출을 관리한다."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, Tool

logger = logging.getLogger("uvicorn.error")


@dataclass
class MCPServerConfig:
    """MCP 서버 연결 설정."""

    name: str
    transport: str  # "stdio" | "sse"
    enabled: bool = True
    # stdio
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    # sse
    url: str | None = None
    headers: dict[str, str] | None = None
    # 도메인 매핑 (선택)
    domain: str | None = None


class MCPConnection:
    """단일 MCP 서버 연결을 관리한다."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.session: ClientSession | None = None
        self.tools: list[Tool] = []
        self._stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        self._stack = AsyncExitStack()
        try:
            if self.config.transport == "stdio":
                if not self.config.command:
                    raise ValueError(f"MCP server '{self.config.name}': stdio requires 'command'")
                params = StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args,
                    env=self.config.env,
                    cwd=self.config.cwd,
                )
                read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
            elif self.config.transport == "sse":
                if not self.config.url:
                    raise ValueError(f"MCP server '{self.config.name}': sse requires 'url'")
                read_stream, write_stream = await self._stack.enter_async_context(
                    sse_client(self.config.url, headers=self.config.headers)
                )
            else:
                raise ValueError(f"Unknown transport: {self.config.transport}")

            self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self.session.initialize()
            result = await self.session.list_tools()
            self.tools = list(result.tools)
            logger.info(
                "MCP server '%s' connected — %d tools discovered",
                self.config.name, len(self.tools),
            )
        except Exception:
            logger.exception("Failed to connect MCP server '%s'", self.config.name)
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception:
                logger.warning("Error closing MCP connection '%s'", self.config.name)
            finally:
                self._stack = None
                self.session = None
                self.tools = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.config.name}' not connected")
        return await self.session.call_tool(tool_name, arguments)

    @property
    def connected(self) -> bool:
        return self.session is not None


class MCPManager:
    """여러 MCP 서버 연결을 중앙 관리한다."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._tool_index: dict[str, str] = {}  # tool_name → server_name

    async def add_server(self, config: MCPServerConfig) -> None:
        if not config.enabled:
            logger.info("MCP server '%s' is disabled, skipping", config.name)
            return
        conn = MCPConnection(config)
        await conn.connect()
        self._connections[config.name] = conn
        for tool in conn.tools:
            self._tool_index[tool.name] = config.name

    async def remove_server(self, name: str) -> None:
        conn = self._connections.pop(name, None)
        if conn:
            tools_to_remove = [t for t, s in self._tool_index.items() if s == name]
            for t in tools_to_remove:
                del self._tool_index[t]
            await conn.disconnect()

    async def disconnect_all(self) -> None:
        for name in list(self._connections.keys()):
            await self.remove_server(name)

    def get_all_tools(self) -> list[tuple[str, Tool]]:
        """(server_name, tool) 쌍 목록을 반환한다."""
        result = []
        for name, conn in self._connections.items():
            for tool in conn.tools:
                result.append((name, tool))
        return result

    def find_tool_server(self, tool_name: str) -> str | None:
        return self._tool_index.get(tool_name)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
        server_name = self._tool_index.get(tool_name)
        if server_name is None:
            raise ValueError(f"Tool '{tool_name}' not found in any MCP server")
        conn = self._connections[server_name]
        return await conn.call_tool(tool_name, arguments)

    @property
    def server_names(self) -> list[str]:
        return list(self._connections.keys())

    @property
    def tool_count(self) -> int:
        return len(self._tool_index)


# ---------------------------------------------------------------------------
# 글로벌 인스턴스
# ---------------------------------------------------------------------------

_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


async def initialize_mcp_servers(configs: list[MCPServerConfig]) -> MCPManager:
    """설정된 MCP 서버에 모두 연결한다. 개별 실패는 로그만 남기고 계속 진행한다."""
    manager = get_mcp_manager()
    for config in configs:
        try:
            await manager.add_server(config)
        except Exception:
            logger.warning("Skipping MCP server '%s' due to connection failure", config.name)
    logger.info(
        "MCP initialization complete: %d servers, %d tools",
        len(manager.server_names), manager.tool_count,
    )
    return manager


async def shutdown_mcp_servers() -> None:
    global _manager
    if _manager:
        await _manager.disconnect_all()
        _manager = None


def call_mcp_tool_sync(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """동기 컨텍스트에서 MCP 도구를 호출한다. FastAPI 엔드포인트에서 사용."""
    manager = get_mcp_manager()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = pool.submit(asyncio.run, manager.call_tool(tool_name, arguments)).result()
    else:
        result = asyncio.run(manager.call_tool(tool_name, arguments))

    if result.isError:
        return f"MCP 도구 실행 오류: {_extract_text(result)}"
    return _extract_text(result)


def _extract_text(result: CallToolResult) -> str:
    """CallToolResult에서 텍스트 내용을 추출한다."""
    texts = []
    for content in result.content:
        if hasattr(content, "text"):
            texts.append(content.text)
    return "\n".join(texts) if texts else "결과가 비어 있습니다."
