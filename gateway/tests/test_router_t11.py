"""T11 — routing/orchestration + T5.5 (docs/06; BUILD_PLAN step 9c). The stock
router over injected fake sub-bots, driven over the wire: menu selection routes to
the right subgraph (T11.1), sticky follow-ups skip the menu (T11.2), the escape
returns to the menu (T11.3), a sub-bot's tool allowlist is unchanged when reached
via the router (T11.6), and an interrupt INSIDE a routed subgraph resumes through
the composite checkpoint (T5.5). Plus the 9c validation rules."""

from __future__ import annotations

import itertools

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END

from app.graphs.emit import ask_quick_replies, resolve_choice
from app.graphs.model import astream_message
from app.graphs.router import MENU_CHOICE, build_router_fragment
from app.graphs.skeleton import GraphFragment, build_bot_graph
from app.graphs.tool_agent import build_tool_agent_fragment
from app.main import create_app
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect


def _canned_bot(text: str) -> GraphFragment:
    """A sub-bot that streams the same answer every turn."""

    def flow(b):
        async def respond(state, config):
            model = GenericFakeChatModel(messages=itertools.cycle([AIMessage(content=text)]))
            full = await astream_message(model, state["messages"])
            return {"messages": [full]}

        b.add_node("respond", respond)
        b.set_entry_after_guard("respond")
        b.add_edge("respond", END)

    return GraphFragment(flow)


def _choice_bot() -> GraphFragment:
    """A sub-bot with its OWN interrupt (T5.5)."""

    def flow(b):
        async def ask(state, config):
            reply = ask_quick_replies(
                "Pick one:", [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
                allow_free_text=False,
            )
            choice = resolve_choice(reply, valid_ids={"x", "y"})
            model = GenericFakeChatModel(messages=iter([AIMessage(content=f"You picked {choice}.")]))
            full = await astream_message(model, state["messages"])
            return {"messages": [full]}

        b.add_node("ask", ask)
        b.set_entry_after_guard("ask")
        b.add_edge("ask", END)

    return GraphFragment(flow)


def _router_cfg(targets, **overrides):
    data = dict(
        id="assistant", name="Assistant", graph="router",
        model={"provider": "fast-small"},
        guard={"enabled": False},
        greeting={"mode": "bot_greeting"},
        routes={"mode": "menu", "sticky": True, "targets": targets},
    )
    data.update(overrides)
    return make_bot(**data)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


def _app(cfg, fragments, sessions):
    fragment = build_router_fragment(cfg, Registry(make_global(), {}), subgraph_fragments=fragments)
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    return create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))


def _quick_replies(events):
    return [e["data"] for e in events if e["data"]["type"] == "quick_replies"]


def _text(events):
    return "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")


async def _drive(app, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, "assistant", body)


TWO_TARGETS = [{"bot": "bot-a", "label": "Bot A"}, {"bot": "bot-b", "label": "Bot B"}]


async def test_t11_menu_sticky_and_escape(sessions):
    cfg = _router_cfg(TWO_TARGETS)
    app = _app(cfg, {"bot-a": _canned_bot("Answer from A."), "bot-b": _canned_bot("Answer from B.")}, sessions)

    # greeting → the menu (one option per target, no free text)
    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    assert [o["label"] for o in menu["options"]] == ["Bot A", "Bot B"]
    assert menu["allow_free_text"] is False
    assert events[-1]["data"]["status"] == "awaiting_input"

    # choose Bot A → handoff prompt (escape option, free text allowed)
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "bot-a"}, "reply_to": menu["reply_to"]})
    [handoff] = _quick_replies(events)
    assert [o["id"] for o in handoff["options"]] == [MENU_CHOICE]
    assert handoff["allow_free_text"] is True

    # T11.1 — the typed question reaches Bot A's subgraph
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "first question"}, "reply_to": handoff["reply_to"]}
    )
    assert _text(events) == "Answer from A."
    [handoff2] = _quick_replies(events)  # back at handoff, escape still one tap away

    # T11.2 — sticky: the follow-up re-enters Bot A, no menu re-shown
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "follow-up"}, "reply_to": handoff2["reply_to"]}
    )
    assert _text(events) == "Answer from A."
    [handoff3] = _quick_replies(events)
    assert [o["id"] for o in handoff3["options"]] == [MENU_CHOICE]  # handoff, NOT the menu

    # T11.3 — the escape returns to the menu…
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": MENU_CHOICE}, "reply_to": handoff3["reply_to"]}
    )
    [menu2] = _quick_replies(events)
    assert [o["id"] for o in menu2["options"]] == ["bot-a", "bot-b"]

    # …and the next choice routes to the OTHER subgraph
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "bot-b"}, "reply_to": menu2["reply_to"]})
    [handoff4] = _quick_replies(events)
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "for B"}, "reply_to": handoff4["reply_to"]}
    )
    assert _text(events) == "Answer from B."


async def test_t5_5_interrupt_inside_routed_subgraph_resumes(sessions):
    cfg = _router_cfg([{"bot": "bot-c", "label": "Bot C"}])
    app = _app(cfg, {"bot-c": _choice_bot()}, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "bot-c"}, "reply_to": menu["reply_to"]})
    [handoff] = _quick_replies(events)

    # the question routes into Bot C, which raises ITS OWN interrupt
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "help me pick"}, "reply_to": handoff["reply_to"]}
    )
    [inner] = _quick_replies(events)
    assert [o["id"] for o in inner["options"]] == ["x", "y"]  # Bot C's interrupt, not the router's
    assert events[-1]["data"]["status"] == "awaiting_input"

    # resuming flows back INTO the subgraph via the composite checkpoint (T5.5),
    # answers, then returns to the router's handoff
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "x"}, "reply_to": inner["reply_to"]})
    assert _text(events) == "You picked x."
    [handoff2] = _quick_replies(events)
    assert [o["id"] for o in handoff2["options"]] == [MENU_CHOICE]


async def test_t11_6_sub_bot_allowlist_unchanged_via_router(sessions):
    """The routed sub-bot is built from ITS OWN config: a hallucinated tool outside
    its allowlist is never executed, exactly as when reached directly."""
    from .test_tool_agent import CALLS, _ScriptedPicker, _bot as _kb_bot_cfg, _client, _kb_server, _tool_call_msg

    CALLS.clear()
    kb_cfg = _kb_bot_cfg()  # allow: [search_kb] — admin_delete exists on the server but is NOT allowlisted
    picker = _ScriptedPicker(responses=[_tool_call_msg("admin_delete", {"target": "everything"})])
    answerer = GenericFakeChatModel(messages=iter([AIMessage(content="No can do.")]))
    kb_fragment = build_tool_agent_fragment(
        kb_cfg, Registry(make_global(), {}),
        mcp_clients=[_client(_kb_server())], agent_model=picker, answer_model=answerer,
    )

    cfg = _router_cfg([{"bot": "kb-bot", "label": "KB"}])
    app = _app(cfg, {"kb-bot": kb_fragment}, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "kb-bot"}, "reply_to": menu["reply_to"]})
    [handoff] = _quick_replies(events)
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "delete everything"}, "reply_to": handoff["reply_to"]}
    )

    assert CALLS == []  # structural scope preserved through the router
    assert _text(events) == "No can do."


async def test_tool_agent_scratch_cleared_between_routed_turns(sessions):
    """Regression (review batch 1): under the router every turn is a resume, so
    scratch is never reset by the runner. The tool-agent must clear its ta_* working
    set at turn end — otherwise turn 2's prompt and CITATIONS include turn 1's
    results ("retrieved for THIS question"), and the round budget is exhausted."""
    import itertools as it

    from mcp.server.fastmcp import FastMCP

    from .test_tool_agent import _ScriptedPicker, _bot as _kb_bot_cfg, _client, _tool_call_msg

    counter = it.count(1)
    server = FastMCP("kb")

    @server.tool()
    async def search_kb(query: str) -> dict:
        """Search (distinct result per call, so turns are distinguishable)."""
        n = next(counter)
        return {"results": [{"title": f"Result {n}", "url": f"https://kb.example/{n}"}]}

    kb_cfg = _kb_bot_cfg()
    picker = _ScriptedPicker(
        responses=[
            _tool_call_msg("search_kb", {"query": "one"}),
            _tool_call_msg("search_kb", {"query": "two"}),
        ]
    )
    answerer = GenericFakeChatModel(messages=itertools.cycle([AIMessage(content="Answer.")]))
    kb_fragment = build_tool_agent_fragment(
        kb_cfg, Registry(make_global(), {}),
        mcp_clients=[_client(server)], agent_model=picker, answer_model=answerer,
    )

    cfg = _router_cfg([{"bot": "kb-bot", "label": "KB"}])
    app = _app(cfg, {"kb-bot": kb_fragment}, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "kb-bot"}, "reply_to": menu["reply_to"]})
    [handoff] = _quick_replies(events)

    # turn 1
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "question one"}, "reply_to": handoff["reply_to"]}
    )
    [sources1] = [e["data"] for e in events if e["data"]["type"] == "sources"]
    assert [s["title"] for s in sources1["sources"]] == ["Result 1"]
    # custom events from INSIDE the routed subgraph reach the wire (runner streams
    # with subgraphs=True — regression: they were silently dropped before)
    assert any(e["data"]["type"] == "status" and e["data"]["state"] == "tool_call" for e in events)
    [handoff2] = _quick_replies(events)

    # turn 2: citations must contain ONLY this turn's result — no carry-over
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "question two"}, "reply_to": handoff2["reply_to"]}
    )
    [sources2] = [e["data"] for e in events if e["data"]["type"] == "sources"]
    assert [s["title"] for s in sources2["sources"]] == ["Result 2"]


# --- 9c validation rules -----------------------------------------------------

def test_router_requires_routes_and_routes_require_router():
    from .test_validation import errs

    no_routes = make_bot(id="r1", graph="router")
    assert [e for e in errs([no_routes]) if "check 14" in e and "routes block" in e]

    target = make_bot(id="t1")
    dead_routes = make_bot(
        id="r2", graph="echo",
        routes={"mode": "menu", "targets": [{"bot": "t1", "label": "T"}]},
    )
    assert [e for e in errs([dead_routes, target]) if "check 14" in e and "must use graph 'router'" in e]


def test_nested_routers_rejected():
    from .test_validation import errs

    leaf = make_bot(id="leaf")
    inner = make_bot(
        id="inner", graph="router",
        routes={"mode": "menu", "targets": [{"bot": "leaf", "label": "L"}]},
    )
    outer = make_bot(
        id="outer", graph="router",
        routes={"mode": "menu", "targets": [{"bot": "inner", "label": "I"}]},
    )
    assert [e for e in errs([leaf, inner, outer]) if "check 10" in e and "nested" in e]
