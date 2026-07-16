"""Prereq E — real guard classifier (docs/06 T4.2) + the TAG_NOSTREAM regression: a
guard's own classification call must NEVER leak into the client's `text` stream (any
model call inside any node is otherwise picked up by stream_mode="messages",
regardless of which node produced it — verified empirically, not hypothetical)."""

from __future__ import annotations

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.graphs.echo import build_echo_fragment
from app.graphs.skeleton import build_bot_graph
from app.main import create_app
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect


def _fake_guard(verdict: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(content=verdict)]))


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


async def _run(cfg, guard_model, sessions, message: str):
    graph = build_bot_graph(
        cfg, [], build_echo_fragment(), sessions.checkpointer, guard_model=guard_model
    )
    reg = Registry(make_global(), {cfg.id: cfg})
    app = create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, cfg.id, {"message": message})


async def test_in_scope_reaches_the_normal_fragment(sessions):
    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    events, _ = await _run(cfg, _fake_guard("in_scope"), sessions, "how do I set up VPN?")
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "You said: how do I set up VPN?"  # the echo fragment ran, not decline


async def test_out_of_scope_routes_to_decline(sessions):
    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    events, _ = await _run(cfg, _fake_guard("out_of_scope"), sessions, "what's the weather?")
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert "outside what I can help with" in text
    assert events[-1]["data"]["status"] == "complete"


async def test_guard_classification_never_leaks_into_the_text_stream(sessions):
    # A guard model that would ALSO leak "in_scope" as its own message content if the
    # TAG_NOSTREAM suppression were missing.
    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    events, _ = await _run(cfg, _fake_guard("in_scope"), sessions, "hi")
    all_text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert "in_scope" not in all_text
    assert "out_of_scope" not in all_text
    assert all_text == "You said: hi"  # ONLY the echo fragment's own text made it through


def test_build_bot_graph_requires_guard_model_when_enabled():
    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    try:
        build_bot_graph(cfg, [], build_echo_fragment(), MemorySaver(), guard_model=None)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "guard_model" in str(e)


# --- Batch 5a: leading-token match + latest-message-only --------------------

async def test_trailing_punctuation_still_declines(sessions):
    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    events, _ = await _run(cfg, _fake_guard("out_of_scope.\n"), sessions, "weather?")
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert "outside what I can help with" in text


async def test_non_conforming_output_fails_open_in_scope(sessions):
    # "out of scope" (spaces, not the token) → leading token "out" → in_scope. Guard
    # is defense-in-depth (golden rule 3); failing open is the documented direction.
    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    events, _ = await _run(cfg, _fake_guard("out of scope"), sessions, "hello")
    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "You said: hello"  # reached the fragment, not decline


async def test_guard_classifies_only_latest_message(sessions):
    """The classifier is invoked with exactly [system, latest HumanMessage] — not the
    whole history — so it can't be steered by earlier turns. We assert the model saw a
    single human message."""
    seen: list[int] = []

    class _Spy(GenericFakeChatModel):
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            # [system, latest] → 2 messages total
            seen.append(len(messages))
            async for c in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield c

        async def ainvoke(self, input, config=None, **kwargs):  # type: ignore[override]
            seen.append(len(input))
            return AIMessage(content="in_scope")

    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    await _run(cfg, _Spy(messages=iter([AIMessage(content="in_scope")])), sessions, "just one")
    assert seen and seen[0] == 2  # system + the single latest human message
