"""IT-helpdesk reference bot — retrieve-then-generate over an in-memory uos_search /
uos_fetch MCP server, with a fake answer model. Proves the fragment wires search →
fetch → answer → sources, delivers identity to the tools via _meta, and never binds
tools to the model (structural scope = zero model tool access)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from mcp import ClientSession
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect

from app.graphs.it_helpdesk import build_it_helpdesk_fragment
from app.graphs.skeleton import build_bot_graph
from app.main import create_app
from app.mcp.transport import StreamableHttpMcpClient
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect

SEEN_IDENTITY: list[dict | None] = []


def _docs_server() -> FastMCP:
    server = FastMCP("uos-docs")

    @server.tool()
    async def uos_search(query: str, ctx: Context) -> dict:
        """Search the Osnabrück University website for content."""
        meta = ctx.request_context.meta
        SEEN_IDENTITY.append((meta.model_dump() if meta else {}).get("identity"))
        return {"results": [
            {"title": "VPN einrichten", "url": "https://www.uni-osnabrueck.de/vpn", "snippet": "Cisco…"},
            {"title": "eduroam", "url": "https://www.uni-osnabrueck.de/eduroam", "snippet": "WLAN…"},
        ]}

    @server.tool()
    async def uos_fetch(url: str) -> str:
        """Fetch page content from a URL and return it as markdown."""
        return f"# Page\nMarkdown content of {url}"

    return server


def _client(server: FastMCP) -> StreamableHttpMcpClient:
    @asynccontextmanager
    async def factory() -> AsyncIterator[ClientSession]:
        async with connect(server) as session:
            await session.initialize()
            yield session

    return StreamableHttpMcpClient(url="mem://uos", session_factory=factory)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


def _bot():
    # guard disabled here to isolate the fragment (guard is covered in test_guard_classifier)
    return make_bot(
        id="it-helpdesk", name="IT-Helpdesk", graph="it-helpdesk",
        model={"provider": "fast-small"},
        tools={"mcp_servers": ["uos-docs"], "allow": ["uos_search", "uos_fetch"], "deny": []},
        guard={"enabled": False},
    )


async def _run(cfg, fragment, sessions, message: str):
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    app = create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, cfg.id, {"message": message})


async def test_retrieve_then_generate_streams_answer_with_sources(sessions):
    SEEN_IDENTITY.clear()
    cfg = _bot()
    answer = GenericFakeChatModel(messages=iter([AIMessage(content="Install the Cisco client.")]))
    fragment = build_it_helpdesk_fragment(cfg, Registry(make_global(), {}), mcp_client=_client(_docs_server()), answer_model=answer)

    events, _ = await _run(cfg, fragment, sessions, "How do I set up the VPN?")
    types = [e["data"]["type"] for e in events]

    # status (tool_call) → streamed text → sources → done
    assert "status" in types
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "Install the Cisco client."

    sources = [e["data"] for e in events if e["data"]["type"] == "sources"]
    assert len(sources) == 1
    titles = [s["title"] for s in sources[0]["sources"]]
    assert titles == ["VPN einrichten", "eduroam"]
    # host derived from url, www stripped
    assert sources[0]["sources"][0]["source"] == "uni-osnabrueck.de"
    # sources bind to the same bubble as the text (Prereq B)
    text_mid = {e["data"]["message_id"] for e in events if e["data"]["type"] == "text"}
    assert sources[0]["message_id"] in text_mid
    assert events[-1]["data"]["status"] == "complete"


async def test_identity_reaches_the_mcp_tools_via_meta(sessions):
    SEEN_IDENTITY.clear()
    cfg = _bot()
    answer = GenericFakeChatModel(messages=iter([AIMessage(content="ok")]))
    fragment = build_it_helpdesk_fragment(cfg, Registry(make_global(), {}), mcp_client=_client(_docs_server()), answer_model=answer)
    await _run(cfg, fragment, sessions, "vpn?")
    # public bot → anonymous identity, but it is still delivered out-of-band via _meta
    assert SEEN_IDENTITY  # uos_search saw the _meta identity payload
    assert SEEN_IDENTITY[0] == {"subject": None, "claims": {}}


def test_fragment_requires_its_tools_in_the_allowlist():
    import pytest

    cfg = make_bot(
        id="it-helpdesk", graph="it-helpdesk",
        tools={"mcp_servers": ["uos-docs"], "allow": ["uos_search"], "deny": []},  # missing uos_fetch
    )
    answer = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    with pytest.raises(ValueError, match="uos_fetch"):
        build_it_helpdesk_fragment(cfg, Registry(make_global(), {}), mcp_client=_client(_docs_server()), answer_model=answer)
