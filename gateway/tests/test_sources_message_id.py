"""Prereq B — sources must bind to the SAME client-facing message_id as their text
(previously: sources carried the raw internal id, unmapped, while text used "m1")."""

from __future__ import annotations

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from app.graphs.emit import emit_sources
from app.graphs.skeleton import BotGraphBuilder, BotState, GraphFragment, _stream_canned, build_bot_graph
from app.main import create_app
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect


def _sources_fragment() -> GraphFragment:
    def flow(b: BotGraphBuilder) -> None:
        async def answer(state: BotState, config: RunnableConfig) -> dict:
            msg = await _stream_canned("Here is the answer.", state["messages"])
            emit_sources(msg.id, [{"title": "Doc", "source": "example.org", "url": "https://example.org"}])
            return {"messages": [msg]}

        b.add_node("answer", answer)
        b.set_entry_after_guard("answer")
        b.add_edge("answer", END)

    return GraphFragment(flow)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


async def test_sources_bind_to_the_same_message_id_as_text(sessions):
    cfg = make_bot(id="echo")
    graph = build_bot_graph(cfg, [], _sources_fragment(), sessions.checkpointer)
    reg = Registry(make_global(), {"echo": cfg})
    app = create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        events, _pings = await collect(client, "echo", {"message": "hi"})

    text_ids = {e["data"]["message_id"] for e in events if e["data"]["type"] == "text"}
    sources_ids = {e["data"]["message_id"] for e in events if e["data"]["type"] == "sources"}
    assert text_ids, "no text events emitted"
    assert sources_ids, "no sources events emitted"
    assert text_ids == sources_ids  # the whole point of the fix
