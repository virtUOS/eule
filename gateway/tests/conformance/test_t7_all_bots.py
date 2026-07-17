"""T7-lite — per-bot protocol conformance, run against EVERY enabled bot in the real
repo config (docs/06 §T7; BUILD_PLAN step 9 gate). Config-only bots have no
bot-specific test code, so this harness is their protocol gate: one turn over the
wire per bot (fake model + fake MCP), asserting the docs/01 invariants.

The fakes are injected by monkeypatching the config→client seams in every consumer
module (`build_chat_model`, `client_for` are imported by name). A new fragment module
that resolves models/MCP from config must be added to _PATCH_TARGETS below — the
harness fails loudly on unpatched network access (placeholder URLs don't resolve).
"""

from __future__ import annotations

import itertools
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect

from app.graphs.factory import GraphCache
from app.main import create_app
from app.mcp.transport import StreamableHttpMcpClient
from app.registry.loader import load_and_validate

from ..conftest import CONFIG_DIR, VALID_ENV
from ..test_protocol_t1 import collect

KNOWN_EVENT_TYPES = {"session", "status", "text", "sources", "quick_replies", "error", "done"}


def _registry():
    result = load_and_validate(CONFIG_DIR, env=VALID_ENV)
    assert result.ok, result.errors
    assert result.registry is not None
    return result.registry


BOT_IDS = [bot_id for bot_id in _registry().ids() if _registry().get(bot_id).enabled]


def _fake_model(*_args, **_kwargs) -> GenericFakeChatModel:
    # Cycles forever: serves the guard ("in_scope…" → verdict in_scope), any picker,
    # and every answer node, however many calls a bot's graph makes.
    return GenericFakeChatModel(
        messages=itertools.cycle([AIMessage(content="in_scope — here is a short answer.")])
    )


def _docs_server() -> FastMCP:
    server = FastMCP("uos-docs")

    @server.tool()
    async def uos_search(query: str) -> dict:
        """Search the university website."""
        return {"results": [{"title": "Page", "url": "https://www.uni.example/p", "snippet": "…"}]}

    @server.tool()
    async def uos_fetch(url: str) -> str:
        """Fetch page content as markdown."""
        return f"# Page\ncontent of {url}"

    @server.tool()
    async def submit_feedback(kind: str, message: str) -> dict:
        """File a feedback/issue ticket."""
        return {"ok": True, "ticket_id": "T-1"}

    return server


def _fake_client(*_args, **_kwargs) -> StreamableHttpMcpClient:
    server = _docs_server()

    @asynccontextmanager
    async def factory() -> AsyncIterator[ClientSession]:
        async with connect(server) as session:
            await session.initialize()
            yield session

    return StreamableHttpMcpClient(url="mem://conformance", session_factory=factory)


# Every module that binds `build_chat_model` / `client_for` by name from config.
_PATCH_TARGETS = [
    ("app.graphs.factory", "build_chat_model", _fake_model),
    ("app.graphs.it_helpdesk", "build_chat_model", _fake_model),
    ("app.graphs.passthrough", "build_chat_model", _fake_model),
    ("app.graphs.tool_agent", "build_chat_model", _fake_model),
    ("app.graphs.it_servicedesk", "build_chat_model", _fake_model),
    ("app.graphs.it_helpdesk", "client_for", _fake_client),
    ("app.graphs.tool_agent", "client_for", _fake_client),
    ("app.graphs.router", "build_chat_model", _fake_model),
    ("app.graphs.it_servicedesk", "client_for", _fake_client),
]


@pytest.fixture
def conformance_app(monkeypatch, sessions):
    import importlib

    for module_name, attr, replacement in _PATCH_TARGETS:
        monkeypatch.setattr(importlib.import_module(module_name), attr, replacement)
    registry = _registry()
    return create_app(registry, sessions=sessions, graphs=GraphCache(registry, sessions))


@pytest.mark.parametrize("bot_id", BOT_IDS)
async def test_t7_protocol_invariants(conformance_app, bot_id):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=conformance_app), base_url="http://test"
    ) as client:
        events, _ = await collect(client, bot_id, {"message": "hello, a quick question"})

    datas = [e["data"] for e in events]

    # docs/01: first event is `session` at seq 0, carrying the bot id
    assert datas[0]["type"] == "session"
    assert datas[0]["seq"] == 0
    assert datas[0]["bot_id"] == bot_id

    # seq is monotonic from 0 with no gaps
    assert [d["seq"] for d in datas] == list(range(len(datas)))

    # every type is in the protocol vocabulary
    assert {d["type"] for d in datas} <= KNOWN_EVENT_TYPES

    # exactly one terminal `done`, and it is last
    dones = [d for d in datas if d["type"] == "done"]
    assert len(dones) == 1 and datas[-1]["type"] == "done"

    # a normal turn with the fakes ends cleanly: either a streamed answer
    # (done: complete) or a pending interrupt (done: awaiting_input — e.g. the
    # router's menu), never an error
    assert not [d for d in datas if d["type"] == "error"]
    assert dones[0]["status"] in ("complete", "awaiting_input")
    if dones[0]["status"] == "complete":
        assert any(d["type"] == "text" for d in datas)
    else:
        assert any(d["type"] == "quick_replies" for d in datas)


def test_every_enabled_bot_is_covered():
    """The harness self-check: nobody quietly ships a bot this file doesn't run."""
    assert BOT_IDS, "no enabled bots found in config/"
    assert set(BOT_IDS) == {b for b in _registry().ids() if _registry().get(b).enabled}
