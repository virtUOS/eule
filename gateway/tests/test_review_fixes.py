"""Regression tests for code-review findings F3, F5, F8 (gateway side)."""

from __future__ import annotations

import httpx
import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from app.graphs.emit import ask_quick_replies
from app.graphs.skeleton import BotGraphBuilder, BotState, GraphFragment, build_bot_graph
from app.main import create_app
from app.registry.validation import check_all

from .conftest import VALID_ENV, make_global
from .test_protocol_t1 import collect


# --- F3: stale pending interrupt cleared on a fresh (non-resume) turn ------

def _menu_fragment() -> GraphFragment:
    def flow(b: BotGraphBuilder) -> None:
        async def menu(state: BotState, config: RunnableConfig) -> dict:
            reply = ask_quick_replies(
                "Pick one",
                [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                allow_free_text=True,
            )
            picked = reply.get("id") or reply.get("text")
            return {"scratch": {**state.get("scratch", {}), "picked": picked}}

        b.add_node("menu", menu)
        b.set_entry_after_guard("menu")
        b.add_edge("menu", END)

    return GraphFragment(flow)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


@pytest.fixture
def menu_client(registry, sessions):
    cfg = registry.get("echo")
    graph = build_bot_graph(cfg, [], _menu_fragment(), sessions.checkpointer)
    app = create_app(registry, sessions=sessions, graphs=_StubGraphs(graph))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_f3_fresh_message_clears_stale_pending(menu_client):
    async with menu_client as client:
        # 1) interrupt turn → quick_replies + done:awaiting_input
        ev1, _ = await collect(client, "echo", {"message": "go"})
        assert "quick_replies" in [e["data"]["type"] for e in ev1]
        qr = next(e["data"] for e in ev1 if e["data"]["type"] == "quick_replies")
        reply_to = qr["reply_to"]
        sid = ev1[0]["data"]["session_id"]

        # 2) a FRESH message on the same session abandons the interrupt
        await collect(client, "echo", {"session_id": sid, "message": "changed my mind"})

        # 3) replaying the old choice must NOT resume — pending was cleared
        ev3, _ = await collect(
            client, "echo", {"session_id": sid, "choice": {"id": "a"}, "reply_to": reply_to}
        )
        assert "no_pending_interrupt" in [e["data"].get("code") for e in ev3]
        assert ev3[-1]["data"]["status"] == "error"


async def test_f3_resume_still_works_normally(menu_client):
    async with menu_client as client:
        ev1, _ = await collect(client, "echo", {"message": "go"})
        qr = next(e["data"] for e in ev1 if e["data"]["type"] == "quick_replies")
        sid = ev1[0]["data"]["session_id"]
        ev2, _ = await collect(
            client, "echo",
            {"session_id": sid, "choice": {"id": "a"}, "reply_to": qr["reply_to"]},
        )
        assert ev2[-1]["data"]["type"] == "done"
        assert ev2[-1]["data"]["status"] == "complete"  # resume succeeds


# --- F5: message_too_long also covers free-text interrupt replies ----------

async def test_f5_choice_text_length_enforced(client):
    resp = await client.post(
        "/api/v1/bots/echo/chat",
        json={"session_id": "s", "choice": {"id": None, "text": "x" * 4001}, "reply_to": "e"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "message_too_long"


async def test_f5_short_choice_text_ok(client):
    # a normal-length free-text reply is not rejected pre-stream
    resp = await client.post(
        "/api/v1/bots/echo/chat",
        json={"session_id": "s", "choice": {"id": None, "text": "hi"}, "reply_to": "e"},
    )
    assert resp.status_code == 200  # streams (will be no_pending_interrupt in-stream)


# --- F8: malformed theme tokens report cleanly, never crash validate-config -

def test_f8_non_hex_token_reports_check9_not_traceback():
    g = make_global()
    g.theme.light["--text"] = "white"  # named colour — not a hex value
    errors, _ = check_all(g, {}, VALID_ENV)  # must not raise
    assert any("check 9" in e and "not a hex" in e for e in errors)


def test_f8_on_primary_auto_without_primary_reports_cleanly():
    g = make_global()
    g.theme.dark["--on-primary"] = "auto"
    del g.theme.dark["--primary"]
    errors, _ = check_all(g, {}, VALID_ENV)  # must not raise KeyError
    assert any("check 9" in e for e in errors)
