"""Stock `passthrough` fragment (BUILD_PLAN step 9 / docs/08 Scenario 3) — streams the
provider with the session history, no tools; `status("thinking")` covers dead air."""

from __future__ import annotations

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.graphs.passthrough import build_passthrough_fragment
from app.graphs.skeleton import build_bot_graph
from app.main import create_app
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


def _bot(**overrides):
    data = dict(
        id="relay", name="Relay", graph="passthrough",
        model={"provider": "fast-small"}, guard={"enabled": False},
    )
    data.update(overrides)
    return make_bot(**data)


async def _run(cfg, fragment, sessions, message: str):
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    app = create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, cfg.id, {"message": message})


async def test_streams_provider_with_thinking_status(sessions):
    cfg = _bot()
    model = GenericFakeChatModel(messages=iter([AIMessage(content="Answer from the backend.")]))
    fragment = build_passthrough_fragment(cfg, Registry(make_global(), {}), answer_model=model)

    events, _ = await _run(cfg, fragment, sessions, "hello")
    datas = [e["data"] for e in events]

    statuses = [d for d in datas if d["type"] == "status"]
    assert statuses and statuses[0]["state"] == "thinking"  # dead-air cover before tokens
    text = "".join(d["delta"] for d in datas if d["type"] == "text")
    assert text == "Answer from the backend."
    assert datas[-1]["status"] == "complete"


class _CapturingModel(GenericFakeChatModel):
    prompts: list[list] = []

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        type(self).prompts.append(list(messages))
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


async def test_optional_system_prompt_prepended_or_absent(sessions):
    _CapturingModel.prompts = []
    cfg = _bot(prompt={"system": "You are a relay."})
    model = _CapturingModel(messages=iter([AIMessage(content="ok")]))
    fragment = build_passthrough_fragment(cfg, Registry(make_global(), {}), answer_model=model)
    await _run(cfg, fragment, sessions, "hi")
    assert _CapturingModel.prompts[0][0].content == "You are a relay."

    # empty prompt.system → nothing prepended (a Scenario-3 backend injects its own)
    _CapturingModel.prompts = []
    cfg2 = _bot(id="relay2", prompt={"system": ""})
    model2 = _CapturingModel(messages=iter([AIMessage(content="ok")]))
    fragment2 = build_passthrough_fragment(cfg2, Registry(make_global(), {}), answer_model=model2)
    await _run(cfg2, fragment2, sessions, "hi")
    assert _CapturingModel.prompts[0][0].content == "hi"
