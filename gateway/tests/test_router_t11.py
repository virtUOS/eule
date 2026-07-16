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


async def test_router_empty_text_reasks_keeps_route(sessions):
    """Batch 5a: empty/whitespace text at the handoff (no escape) re-asks and keeps
    the route sticky — it does NOT silently bounce to the menu."""
    cfg = _router_cfg([{"bot": "bot-a", "label": "Bot A"}])
    app = _app(cfg, {"bot-a": _canned_bot("Answer from A.")}, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "bot-a"}, "reply_to": menu["reply_to"]})
    [handoff] = _quick_replies(events)

    # empty text at the handoff → re-ask (still the handoff, escape option present)
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "   "}, "reply_to": handoff["reply_to"]}
    )
    assert not [e for e in events if e["data"]["type"] == "text"]  # no sub-bot answer
    [reask] = _quick_replies(events)
    assert [o["id"] for o in reask["options"]] == [MENU_CHOICE]  # handoff, not menu

    # a real question now still routes to Bot A (route stayed sticky)
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "real q"}, "reply_to": reask["reply_to"]}
    )
    assert _text(events) == "Answer from A."


async def test_router_invalid_menu_reply_reshows_menu_not_error(sessions):
    """Batch 5a: a free-text / invalid id at the menu must re-show the menu, not crash
    the turn into internal_error (resolve_choice used to raise)."""
    cfg = _router_cfg([{"bot": "bot-a", "label": "Bot A"}])
    app = _app(cfg, {"bot-a": _canned_bot("Answer from A.")}, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)

    # reply with a bogus id (menu is allow_free_text=False, but a client could)
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": "nonexistent"}, "reply_to": menu["reply_to"]}
    )
    assert not [e for e in events if e["data"]["type"] == "error"]
    [menu2] = _quick_replies(events)
    assert [o["id"] for o in menu2["options"]] == ["bot-a"]  # menu re-shown
    assert events[-1]["data"]["status"] == "awaiting_input"


# --- Step 12: classifier routing ----------------------------------------------

from .test_metrics_step11 import sample  # noqa: E402
from .test_tool_agent import _ScriptedPicker  # noqa: E402  (generate-only scripted fake)


class _RaisingClassifier(_ScriptedPicker):
    def _generate(self, *args, **kwargs):  # type: ignore[override]
        self.calls += 1
        raise RuntimeError("model down")


def _classifier_cfg(targets, **overrides):
    return _router_cfg(targets, routes={"mode": "classifier", "sticky": True, "targets": targets}, **overrides)


def _classifier_app(cfg, fragments, classifier, sessions):
    fragment = build_router_fragment(
        cfg, Registry(make_global(), {}), subgraph_fragments=fragments, classifier_model=classifier,
    )
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    return create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))


async def test_classifier_types_at_menu_routes_and_answers_in_one_turn(sessions):
    cfg = _classifier_cfg(TWO_TARGETS)
    classifier = _ScriptedPicker(responses=[AIMessage(content="bot-a")])
    app = _classifier_app(cfg, {"bot-a": _canned_bot("Answer from A."), "bot-b": _canned_bot("Answer from B.")}, classifier, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    assert menu["allow_free_text"] is True  # classifier mode: typing is allowed

    # typing instead of clicking → classified → routed → answered, ONE turn
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "my vpn is broken"}, "reply_to": menu["reply_to"]}
    )
    assert classifier.calls == 1
    assert _text(events) == "Answer from A."
    statuses = [e["data"]["label"] for e in events if e["data"]["type"] == "status"]
    assert any("→ Bot A" in s for s in statuses)  # routed-lane transparency
    [handoff] = _quick_replies(events)  # lands in the normal sticky loop
    assert [o["id"] for o in handoff["options"]] == [MENU_CHOICE]


async def test_classifier_none_falls_back_to_menu_and_click_needs_no_retype(sessions):
    cfg = _classifier_cfg(TWO_TARGETS)
    classifier = _ScriptedPicker(responses=[AIMessage(content="none")])
    app = _classifier_app(cfg, {"bot-a": _canned_bot("Answer from A."), "bot-b": _canned_bot("Answer from B.")}, classifier, sessions)

    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)

    none_before = sample("router_classifier_outcomes_total", {"router_bot": "assistant", "outcome": "none"})
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "hard to classify"}, "reply_to": menu["reply_to"]}
    )
    assert not [e for e in events if e["data"]["type"] == "text"]  # no answer yet
    [menu2] = _quick_replies(events)  # menu re-shown
    assert [o["id"] for o in menu2["options"]] == ["bot-a", "bot-b"]
    assert sample("router_classifier_outcomes_total", {"router_bot": "assistant", "outcome": "none"}) == none_before + 1

    # clicking now consumes the KEPT question — the sub-bot answers with no retyping
    events, _ = await _drive(app, {"session_id": sid, "choice": {"id": "bot-b"}, "reply_to": menu2["reply_to"]})
    assert _text(events) == "Answer from B."


async def test_classifier_garbage_and_exception_fall_back_to_menu(sessions):
    cfg = _classifier_cfg(TWO_TARGETS)
    fragments = {"bot-a": _canned_bot("A."), "bot-b": _canned_bot("B.")}

    # garbage token → unparseable → menu
    garbage = _ScriptedPicker(responses=[AIMessage(content="I think bot-a would be great!?")])
    app = _classifier_app(cfg, fragments, garbage, sessions)
    events, _ = await _drive(app, {"greeting": True})
    sid = events[0]["data"]["session_id"]
    [menu] = _quick_replies(events)
    before = sample("router_classifier_outcomes_total", {"router_bot": "assistant", "outcome": "unparseable"})
    events, _ = await _drive(
        app, {"session_id": sid, "choice": {"id": None, "text": "q"}, "reply_to": menu["reply_to"]}
    )
    assert _quick_replies(events)[0]["options"][0]["id"] == "bot-a"  # menu again
    assert sample("router_classifier_outcomes_total", {"router_bot": "assistant", "outcome": "unparseable"}) == before + 1

    # model exception → error outcome → menu, never internal_error
    raising = _RaisingClassifier(responses=[AIMessage(content="unused")])
    sessions2 = type(sessions)(clock=lambda: 0.0, id_factory=iter(["s1", "s2", "s3"]).__next__)
    app2 = _classifier_app(cfg, fragments, raising, sessions2)
    events, _ = await _drive(app2, {"greeting": True})
    sid2 = events[0]["data"]["session_id"]
    [menu2] = _quick_replies(events)
    err_before = sample("router_classifier_outcomes_total", {"router_bot": "assistant", "outcome": "error"})
    events, _ = await _drive(
        app2, {"session_id": sid2, "choice": {"id": None, "text": "q"}, "reply_to": menu2["reply_to"]}
    )
    assert not [e for e in events if e["data"]["type"] == "error"]
    assert _quick_replies(events)  # menu re-shown
    assert sample("router_classifier_outcomes_total", {"router_bot": "assistant", "outcome": "error"}) == err_before + 1


async def test_context_topic_shortcut_routes_without_model_call(sessions):
    cfg = _classifier_cfg(TWO_TARGETS)
    classifier = _ScriptedPicker(responses=[AIMessage(content="never-consulted")])
    app = _classifier_app(cfg, {"bot-a": _canned_bot("Answer from A."), "bot-b": _canned_bot("B.")}, classifier, sessions)

    ctx_before = sample("router_choices_total", {"router_bot": "assistant", "target": "bot-a", "method": "context"})
    # a FRESH message turn (no session) carrying the step-8 topic hint
    events, _ = await _drive(app, {"message": "when is it open?", "context": {"topic": "bot-a"}})
    assert classifier.calls == 0  # deterministic rung: zero model calls
    assert _text(events) == "Answer from A."
    assert sample("router_choices_total", {"router_bot": "assistant", "target": "bot-a", "method": "context"}) == ctx_before + 1


async def test_fresh_typed_message_is_classified_directly(sessions):
    """No greeting, no menu: a first-contact typed message routes in one turn."""
    cfg = _classifier_cfg(TWO_TARGETS)
    classifier = _ScriptedPicker(responses=[AIMessage(content="bot-b")])
    app = _classifier_app(cfg, {"bot-a": _canned_bot("A."), "bot-b": _canned_bot("Answer from B.")}, classifier, sessions)

    events, _ = await _drive(app, {"message": "study question"})
    assert classifier.calls == 1
    assert _text(events) == "Answer from B."
    [handoff] = _quick_replies(events)
    assert [o["id"] for o in handoff["options"]] == [MENU_CHOICE]


async def test_greeting_with_topic_skips_menu_to_handoff(sessions):
    cfg = _classifier_cfg(TWO_TARGETS)
    classifier = _ScriptedPicker(responses=[AIMessage(content="unused")])
    app = _classifier_app(cfg, {"bot-a": _canned_bot("A."), "bot-b": _canned_bot("B.")}, classifier, sessions)

    events, _ = await _drive(app, {"greeting": True, "context": {"topic": "bot-b"}})
    assert classifier.calls == 0
    [handoff] = _quick_replies(events)  # not the menu: straight to "what's your question?"
    assert [o["id"] for o in handoff["options"]] == [MENU_CHOICE]


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
