"""Streamable-HTTP MCP transport (docs/04 §7, docs/08). Concrete `McpClient` over the
official MCP SDK.

Connection lifecycle is per-call: each `list_tools`/`call` opens a fresh session,
initializes, does its work, and closes. Stateless and robust to disconnects; the cost is
one connect+initialize handshake per call. A pooled/persistent session is a future
optimization (single-instance v1 — keep it boring, docs/00).

Identity is delivered out-of-band via the MCP `_meta` request field (`call_tool(...,
meta=...)`) — never as a tool argument (the model can't name or forge `_meta`, and a
FastMCP server silently drops an extra `_identity` argument). The gateway's static bearer
token (authenticating the gateway TO the server) rides the HTTP Authorization header.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, AsyncContextManager, AsyncIterator, Callable

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .client import McpResult, McpToolSpec

SessionFactory = Callable[[], AsyncContextManager[ClientSession]]


def _text_of(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


class StreamableHttpMcpClient:
    """Implements the `McpClient` protocol (mcp/client.py) over streamable-HTTP."""

    def __init__(
        self,
        url: str,
        *,
        bearer_token: str | None = None,
        timeout_s: int = 20,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._url = url
        self._bearer_token = bearer_token
        self._timeout_s = timeout_s
        # Test seam: inject a factory yielding an already-initialized ClientSession
        # (e.g. the in-memory FastMCP harness). Production uses the default below.
        self._session_factory = session_factory or self._default_session_factory

    @asynccontextmanager
    async def _default_session_factory(self) -> AsyncIterator[ClientSession]:
        headers = {"Authorization": f"Bearer {self._bearer_token}"} if self._bearer_token else None
        async with streamablehttp_client(
            self._url, headers=headers, timeout=timedelta(seconds=self._timeout_s)
        ) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[McpToolSpec]:
        async with self._session_factory() as session:
            result = await session.list_tools()
            return [
                McpToolSpec(
                    name=t.name,
                    description=t.description or "",
                    input_schema=t.inputSchema or {"type": "object", "properties": {}},
                )
                for t in result.tools
            ]

    async def call(
        self, tool_name: str, arguments: dict[str, Any], *, identity: dict[str, Any] | None
    ) -> McpResult:
        # Identity → `_meta`, structurally separate from the model-authored `arguments`.
        meta = {"identity": identity} if identity is not None else None
        async with self._session_factory() as session:
            result = await session.call_tool(tool_name, arguments, meta=meta)
            return McpResult(
                is_error=bool(getattr(result, "isError", False)),
                structured=getattr(result, "structuredContent", None),
                text=_text_of(result),
            )
