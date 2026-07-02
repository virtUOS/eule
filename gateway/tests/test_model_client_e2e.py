"""Prereq D — proves a REAL ChatOpenAI client streams through the full gateway pipeline
exactly like the fake model does (mocked HTTP transport, no network). This is the
integration proof for the "OpenAI-compatible == vLLM == a third-party bot's endpoint"
claim in docs/08 scenario 3 — the gateway genuinely cannot tell them apart."""

from __future__ import annotations

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from app.graphs.model import build_chat_model
from app.graphs.skeleton import BotGraphBuilder, BotState, GraphFragment, build_bot_graph
from app.main import create_app
from app.registry.registry import Registry, ResolvedProvider

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect

_SSE_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m",'
    '"choices":[{"index":0,"delta":{"role":"assistant","content":"Hello "},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m",'
    '"choices":[{"index":0,"delta":{"content":"world"},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m",'
    '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)


def _mock_openai_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_SSE_BODY.encode())

    return httpx.MockTransport(handler)


def _real_model_fragment(model: object) -> GraphFragment:
    """Streams via astream+merge — the same pattern `_stream_canned` uses — so
    LangGraph's `stream_mode="messages"` observes each token as it's produced,
    rather than a single chunk after the fact."""

    def flow(b: BotGraphBuilder) -> None:
        async def answer(state: BotState, config: RunnableConfig) -> dict:
            chunks = [c async for c in model.astream(state["messages"])]  # type: ignore[attr-defined]
            full = chunks[0]
            for c in chunks[1:]:
                full = full + c
            return {"messages": [full]}

        b.add_node("answer", answer)
        b.set_entry_after_guard("answer")
        b.add_edge("answer", END)

    return GraphFragment(flow)


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


async def test_real_model_client_streams_through_the_gateway_pipeline(sessions):
    provider = ResolvedProvider(
        name="default", base_url="http://mock/v1", api_key="k",
        default_model="m", timeout_s=30, max_retries=0,
    )
    model = build_chat_model(
        provider, http_async_client=httpx.AsyncClient(transport=_mock_openai_transport())
    )

    cfg = make_bot(id="echo")
    graph = build_bot_graph(cfg, [], _real_model_fragment(model), sessions.checkpointer)
    reg = Registry(make_global(), {"echo": cfg})
    app = create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        events, _pings = await collect(client, "echo", {"message": "hi"})

    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "Hello world"
    assert events[-1]["data"]["type"] == "done"
    assert events[-1]["data"]["status"] == "complete"
