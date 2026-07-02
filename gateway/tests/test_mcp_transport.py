"""Real MCP transport against an in-memory FastMCP server (no live HTTP needed).

Proves the streamable-HTTP client's session logic: tool discovery, calling with model
`arguments`, and — SECURITY-CRITICAL — that identity is delivered via MCP `_meta` (which
the server actually receives) and NOT as a tool argument (which FastMCP silently drops).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect

from app.mcp.client import McpResult, mcp_call
from app.mcp.transport import StreamableHttpMcpClient
from app.runtime.context import Identity, RuntimeContext

from .conftest import make_bot


def _server() -> FastMCP:
    server = FastMCP("test-docs")

    @server.tool()
    async def search(query: str, ctx: Context) -> dict:
        """Search the documentation."""
        meta = ctx.request_context.meta
        seen = meta.model_dump() if meta else None
        return {"query": query, "identity_seen": (seen or {}).get("identity")}

    @server.tool()
    def admin_wipe(target: str) -> dict:
        """A dangerous write tool that a read-only bot must never bind."""
        return {"wiped": target}

    return server


def _payload(result: McpResult) -> Any:
    """A dict-returning FastMCP tool sends its result as JSON text (structuredContent is
    populated only when the server declares an output schema). Prefer structured, else
    parse the text — this is what build_mcp_tool's `_run` effectively hands the model."""
    return result.structured if result.structured is not None else json.loads(result.text)


def _client(server: FastMCP) -> StreamableHttpMcpClient:
    @asynccontextmanager
    async def factory() -> AsyncIterator[ClientSession]:
        async with connect(server) as session:
            await session.initialize()
            yield session

    return StreamableHttpMcpClient(url="mem://test", session_factory=factory)


async def test_list_tools_discovers_specs():
    client = _client(_server())
    specs = {s.name: s for s in await client.list_tools()}
    assert set(specs) == {"search", "admin_wipe"}
    assert specs["search"].description.startswith("Search the documentation")
    assert "query" in specs["search"].input_schema["properties"]
    # identity is NOT part of any tool's declared input schema
    assert "identity" not in specs["search"].input_schema.get("properties", {})
    assert "_identity" not in specs["search"].input_schema.get("properties", {})


async def test_call_delivers_model_args_and_identity_via_meta():
    client = _client(_server())
    result = await client.call(
        "search", {"query": "vpn setup"}, identity={"subject": "alice", "claims": {"sub": "alice"}}
    )
    assert isinstance(result, McpResult)
    assert result.is_error is False
    # the server received the identity via _meta (not as an argument)
    assert _payload(result) == {"query": "vpn setup", "identity_seen": {"subject": "alice", "claims": {"sub": "alice"}}}


async def test_call_without_identity_sends_no_meta():
    client = _client(_server())
    result = await client.call("search", {"query": "x"}, identity=None)
    assert _payload(result)["identity_seen"] is None


async def test_mcp_call_wrapper_routes_ctx_identity_to_the_server():
    """End-to-end through the sanctioned wrapper: ctx identity reaches the server, and a
    model-smuggled `subject` argument does NOT become the identity."""
    cfg = make_bot()
    ctx = RuntimeContext(
        bot_id=cfg.id, config=cfg,
        identity=Identity(authenticated=True, subject="real-user", claims={"sub": "real-user"}, roles=[]),
        session_id="s", request_id="r", locale="en",
    )
    client = _client(_server())
    result = await mcp_call(ctx, client, "search", query="hi", subject="attacker")
    # server saw the TRUSTED identity via _meta, not the smuggled "attacker"
    assert _payload(result)["identity_seen"] == {"subject": "real-user", "claims": {"sub": "real-user"}}


async def test_unknown_tool_surfaces_as_error_not_crash():
    client = _client(_server())
    result = await client.call("does_not_exist", {}, identity=None)
    assert result.is_error is True
