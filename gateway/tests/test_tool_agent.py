"""Stock `tool-agent` fragment (BUILD_PLAN step 9) — bounded model-driven tool loop
over an in-memory MCP server. Proves: allowlist scoping (a hallucinated tool is never
executed), the round bound (default 1: tool output reaches only the final generate),
identity via _meta, NOSTREAM tool selection (no leak into the text stream), and
sources only from `sources_from`."""

from __future__ import annotations

import itertools
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage
from mcp import ClientSession
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect

from app.graphs.skeleton import build_bot_graph
from app.graphs.tool_agent import build_tool_agent_fragment
from app.main import create_app
from app.mcp.transport import StreamableHttpMcpClient
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect

CALLS: list[tuple[str, dict | None]] = []  # (tool, _meta identity) per executed call


def _kb_server() -> FastMCP:
    server = FastMCP("kb")

    @server.tool()
    async def search_kb(query: str, ctx: Context) -> dict:
        """Search the knowledge base."""
        meta = ctx.request_context.meta
        CALLS.append(("search_kb", (meta.model_dump() if meta else {}).get("identity")))
        return {"results": [
            {"title": "Library hours", "url": "https://www.uni.example/library", "snippet": "8-22"},
        ]}

    @server.tool()
    async def admin_delete(target: str) -> str:
        """Dangerous admin tool — never allowlisted for this bot."""
        CALLS.append(("admin_delete", None))
        return "deleted"

    return server


def _client(server: FastMCP) -> StreamableHttpMcpClient:
    @asynccontextmanager
    async def factory() -> AsyncIterator[ClientSession]:
        async with connect(server) as session:
            await session.initialize()
            yield session

    return StreamableHttpMcpClient(url="mem://kb", session_factory=factory)


def _bot(**overrides):
    data = dict(
        id="kb-bot", name="KB Bot", graph="tool-agent",
        model={"provider": "fast-small"},
        tools={"mcp_servers": ["kb"], "allow": ["search_kb"], "deny": []},
        guard={"enabled": False},
        graph_params={"sources_from": ["search_kb"]},
    )
    data.update(overrides)
    return make_bot(**data)


def _tool_call_msg(name: str, args: dict, content: str = "Selecting a tool.") -> AIMessage:
    return AIMessage(content=content, tool_calls=[{"name": name, "args": args, "id": "tc1"}])


# The picker fake must be generate-only: GenericFakeChatModel's streaming path drops
# tool_calls (it only streams content tokens), while real OpenAI streams carry
# tool-call chunks. FakeMessagesListChatModel returns the scripted message verbatim.
class _ScriptedPicker(FakeMessagesListChatModel):
    calls: int = 0

    def _generate(self, *args, **kwargs):  # type: ignore[override]
        self.calls += 1
        return super()._generate(*args, **kwargs)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


async def _run(cfg, fragment, sessions, message: str):
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    app = create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, cfg.id, {"message": message})


def _fragment(cfg, picker_msgs, answer="The library is open 8-22."):
    """Returns (fragment, picker) — assert on picker.calls to prove the round bound."""
    picker = _ScriptedPicker(responses=list(picker_msgs))
    answerer = GenericFakeChatModel(messages=iter([AIMessage(content=answer)]))
    fragment = build_tool_agent_fragment(
        cfg, Registry(make_global(), {}),
        mcp_clients=[_client(_kb_server())], agent_model=picker, answer_model=answerer,
    )
    return fragment, picker


async def test_one_round_search_then_answer_with_sources(sessions):
    CALLS.clear()
    cfg = _bot()
    fragment, picker = _fragment(cfg, [_tool_call_msg("search_kb", {"query": "library"})])

    events, _ = await _run(cfg, fragment, sessions, "When is the library open?")
    types = [e["data"]["type"] for e in events]

    assert [c[0] for c in CALLS] == ["search_kb"]
    assert picker.calls == 1  # default max_tool_rounds=1: the model is NOT re-entered
    assert "status" in types
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "The library is open 8-22."

    sources = [e["data"] for e in events if e["data"]["type"] == "sources"]
    assert len(sources) == 1
    assert sources[0]["sources"] == [
        {"title": "Library hours", "source": "uni.example", "url": "https://www.uni.example/library"}
    ]
    text_mid = {e["data"]["message_id"] for e in events if e["data"]["type"] == "text"}
    assert sources[0]["message_id"] in text_mid
    assert events[-1]["data"]["status"] == "complete"


async def test_selection_preamble_never_leaks_into_text_stream(sessions):
    CALLS.clear()
    cfg = _bot()
    # the picker "thinks out loud" — its content must NOT reach the client (NOSTREAM)
    fragment, _picker = _fragment(
        cfg, [_tool_call_msg("search_kb", {"query": "x"}, content="I will now search the KB!")]
    )
    events, _ = await _run(cfg, fragment, sessions, "hours?")
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert "I will now search" not in text
    assert text == "The library is open 8-22."


async def test_hallucinated_tool_outside_allowlist_is_never_executed(sessions):
    CALLS.clear()
    cfg = _bot()
    # the model asks for a tool the server HAS but the bot does not allowlist
    fragment, _picker = _fragment(cfg, [_tool_call_msg("admin_delete", {"target": "everything"})])
    events, _ = await _run(cfg, fragment, sessions, "delete everything")

    assert CALLS == []  # structurally impossible, not "declined"
    assert events[-1]["data"]["status"] == "complete"  # degrades to a no-tools answer


async def test_no_tool_calls_goes_straight_to_generate(sessions):
    CALLS.clear()
    cfg = _bot()
    fragment, _picker = _fragment(cfg, [AIMessage(content="I can answer directly.")])  # no tools
    events, _ = await _run(cfg, fragment, sessions, "hello")
    assert CALLS == []
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "The library is open 8-22."
    # no sources: nothing was retrieved
    assert not [e for e in events if e["data"]["type"] == "sources"]


async def test_opt_in_second_round_re_enters_the_model(sessions):
    CALLS.clear()
    cfg = _bot(graph_params={"max_tool_rounds": 2, "sources_from": ["search_kb"]})
    # two selection rounds scripted; the second sees round-1 results in context
    fragment, picker = _fragment(
        cfg,
        [
            _tool_call_msg("search_kb", {"query": "first"}),
            _tool_call_msg("search_kb", {"query": "refined"}),
        ],
    )
    events, _ = await _run(cfg, fragment, sessions, "complex question")
    assert [c[0] for c in CALLS] == ["search_kb", "search_kb"]
    assert picker.calls == 2  # opt-in re-entry happened, and no third round
    assert events[-1]["data"]["status"] == "complete"


async def test_identity_reaches_tools_via_meta(sessions):
    CALLS.clear()
    cfg = _bot()
    fragment, _picker = _fragment(cfg, [_tool_call_msg("search_kb", {"query": "x"})])
    await _run(cfg, fragment, sessions, "hours?")
    # public bot → anonymous, but identity is still delivered out-of-band (docs/04 §7)
    assert CALLS[0][1] == {"subject": None, "claims": {}}


def test_empty_effective_allowlist_fails_at_build():
    cfg = _bot(tools={"mcp_servers": ["kb"], "allow": ["search_kb"], "deny": ["search_kb"]}, graph_params={})
    with pytest.raises(ValueError, match="non-empty"):
        build_tool_agent_fragment(
            cfg, Registry(make_global(), {}),
            mcp_clients=[_client(_kb_server())],
            agent_model=GenericFakeChatModel(messages=iter([])),
        )


async def test_tool_result_text_is_bounded(sessions):
    """max_tool_result_chars caps what an oversized/hostile tool result contributes."""
    CALLS.clear()
    server = FastMCP("kb")

    @server.tool()
    async def search_kb(query: str) -> str:
        """Search."""
        CALLS.append(("search_kb", None))
        return "A" * 50_000

    cfg = _bot(graph_params={"max_tool_result_chars": 200, "sources_from": []})
    picker = _ScriptedPicker(responses=[_tool_call_msg("search_kb", {"query": "x"})])

    captured: list[str] = []

    class _CapturingAnswerer(GenericFakeChatModel):
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            captured.append(str(messages[-1].content))
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk

    answerer = _CapturingAnswerer(messages=iter([AIMessage(content="ok")]))
    fragment = build_tool_agent_fragment(
        cfg, Registry(make_global(), {}),
        mcp_clients=[_client(server)], agent_model=picker, answer_model=answerer,
    )
    events, _ = await _run(cfg, fragment, sessions, "q")
    assert events[-1]["data"]["status"] == "complete"
    assert captured and len(captured[0]) < 1000  # 200-char result + framing, not 50k
