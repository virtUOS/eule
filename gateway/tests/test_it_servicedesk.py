"""IT service-desk bot (BUILD_PLAN step 13) — menu-first bespoke fragment over an
in-memory MCP server hosting uos_search / uos_fetch / submit_feedback. Exercises the
three lanes: find info (retrieve-then-generate), call support (actions event), and the
feedback wizard (kind → description → submit)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect

from app.graphs.it_servicedesk import build_it_servicedesk_fragment
from app.graphs.skeleton import build_bot_graph
from app.main import create_app
from app.mcp.transport import StreamableHttpMcpClient
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect

SUBMITTED: list[dict] = []


def _server() -> FastMCP:
    server = FastMCP("desk")

    @server.tool()
    async def uos_search(query: str) -> dict:
        """Search the university website."""
        return {"results": [{"title": "VPN", "url": "https://www.uni.example/vpn", "snippet": "…"}]}

    @server.tool()
    async def uos_fetch(url: str) -> str:
        """Fetch page markdown."""
        return f"# Page\n{url}"

    @server.tool()
    async def submit_feedback(kind: str, message: str) -> dict:
        """File a feedback ticket."""
        SUBMITTED.append({"kind": kind, "message": message})
        return {"ok": True, "ticket_id": "T-42"}

    return server


def _client() -> StreamableHttpMcpClient:
    @asynccontextmanager
    async def factory() -> AsyncIterator[ClientSession]:
        async with connect(_server()) as session:
            await session.initialize()
            yield session

    return StreamableHttpMcpClient(url="mem://desk", session_factory=factory)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


def _bot(**overrides):
    data = dict(
        id="it-servicedesk", name="Service Desk", graph="it-servicedesk",
        model={"provider": "fast-small"},
        tools={"mcp_servers": ["uos-docs", "uos-helpdesk"],
               "allow": ["uos_search", "uos_fetch", "submit_feedback"], "deny": []},
        guard={"enabled": False},
        graph_params={"phone": "+49 541 969 0000", "phone_label": "IT-Service-Desk",
                      "portal_url": "https://www.uni.example/portal"},
    )
    data.update(overrides)
    return make_bot(**data)


def _app(cfg, sessions, answer="Here is the answer."):
    import itertools

    model = GenericFakeChatModel(messages=itertools.cycle([AIMessage(content=answer)]))
    fragment = build_it_servicedesk_fragment(
        cfg, Registry(make_global(), {}), mcp_clients=[_client()], answer_model=model,
    )
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    return create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))


async def _drive(app, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, "it-servicedesk", body)


def _qr(events):
    return [e["data"] for e in events if e["data"]["type"] == "quick_replies"]


def _text(events):
    return "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")


async def test_greeting_opens_the_three_option_menu(sessions):
    events, _ = await _drive(_app(_bot(), sessions), {"greeting": True})
    [menu] = _qr(events)
    assert [o["id"] for o in menu["options"]] == ["info", "call", "feedback"]
    assert menu["allow_free_text"] is False
    assert events[-1]["data"]["status"] == "awaiting_input"


async def test_typed_question_shortcuts_to_find_info(sessions):
    events, _ = await _drive(_app(_bot(), sessions), {"message": "how do I set up the VPN?"})
    assert _text(events) == "Here is the answer."
    sources = [e["data"] for e in events if e["data"]["type"] == "sources"]
    assert sources and sources[0]["sources"][0]["title"] == "VPN"
    assert _qr(events)[-1]["options"][0]["id"] == "info"  # back to the menu


async def test_menu_info_asks_then_answers(sessions):
    app = _app(_bot(), sessions)
    ev, _ = await _drive(app, {"greeting": True})
    sid = ev[0]["data"]["session_id"]
    [menu] = _qr(ev)
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": "info"}, "reply_to": menu["reply_to"]})
    [ask] = _qr(ev)  # "what would you like to know?"
    assert ask["allow_free_text"] is True
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": None, "text": "vpn?"}, "reply_to": ask["reply_to"]})
    assert _text(ev) == "Here is the answer."


async def test_call_support_emits_actions(sessions):
    app = _app(_bot(), sessions)
    ev, _ = await _drive(app, {"greeting": True})
    sid = ev[0]["data"]["session_id"]
    [menu] = _qr(ev)
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": "call"}, "reply_to": menu["reply_to"]})
    actions = [e["data"] for e in ev if e["data"]["type"] == "actions"]
    assert len(actions) == 1
    kinds = [(a["kind"], a["value"]) for a in actions[0]["actions"]]
    assert ("tel", "+49 541 969 0000") in kinds
    assert ("url", "https://www.uni.example/portal") in kinds
    assert _qr(ev)[-1]["options"][0]["id"] == "info"  # back to the menu


async def test_feedback_wizard_submits_via_mcp(sessions):
    from .test_metrics_step11 import sample

    SUBMITTED.clear()
    metric_before = sample("feedback_submitted_total", {"bot": "it-servicedesk", "kind": "negative"})
    app = _app(_bot(), sessions)
    ev, _ = await _drive(app, {"greeting": True})
    sid = ev[0]["data"]["session_id"]
    [menu] = _qr(ev)
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": "feedback"}, "reply_to": menu["reply_to"]})
    [kind] = _qr(ev)
    assert [o["id"] for o in kind["options"]] == ["positive", "negative", "request", "__menu__"]
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": "negative"}, "reply_to": kind["reply_to"]})
    [desc] = _qr(ev)
    assert desc["allow_free_text"] is True
    ev, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "the wifi keeps dropping"}, "reply_to": desc["reply_to"]}
    )
    assert SUBMITTED == [{"kind": "negative", "message": "the wifi keeps dropping"}]
    assert "Danke" in _text(ev) or "Thanks" in _text(ev)
    assert _qr(ev)[-1]["options"][0]["id"] == "info"  # back to the menu
    assert sample("feedback_submitted_total", {"bot": "it-servicedesk", "kind": "negative"}) == metric_before + 1


async def test_feedback_cancel_returns_to_menu_without_submitting(sessions):
    SUBMITTED.clear()
    app = _app(_bot(), sessions)
    ev, _ = await _drive(app, {"greeting": True})
    sid = ev[0]["data"]["session_id"]
    [menu] = _qr(ev)
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": "feedback"}, "reply_to": menu["reply_to"]})
    [kind] = _qr(ev)
    ev, _ = await _drive(app, {"session_id": sid, "choice": {"id": "__menu__"}, "reply_to": kind["reply_to"]})
    assert SUBMITTED == []
    assert [o["id"] for o in _qr(ev)[-1]["options"]] == ["info", "call", "feedback"]  # menu


def test_missing_tool_in_allowlist_fails_at_build():
    import pytest

    cfg = _bot(tools={"mcp_servers": ["uos-docs"], "allow": ["uos_search", "uos_fetch"], "deny": []})
    with pytest.raises(ValueError, match="submit_feedback"):
        build_it_servicedesk_fragment(
            cfg, Registry(make_global(), {}), mcp_clients=[_client()],
            answer_model=GenericFakeChatModel(messages=iter([AIMessage(content="x")])),
        )
