"""BUILD_PLAN step 9a — the askUOS bot: stock passthrough over a FAKE
OpenAI-compatible endpoint (httpx MockTransport, no network). Proves the 9a
decisions end-to-end: stateless history (capped at history_max_turns), `language`
via extra_body mapped from the request locale (omitted when unmapped), streaming
through the full gateway pipeline."""

from __future__ import annotations

import json

import httpx

from app.graphs.model import build_chat_model
from app.graphs.passthrough import build_passthrough_fragment
from app.graphs.skeleton import build_bot_graph
from app.main import create_app
from app.registry.registry import Registry, ResolvedProvider

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect

_SSE_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"askUOS-agent",'
    '"choices":[{"index":0,"delta":{"role":"assistant","content":"Die Bewerbung "},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"askUOS-agent",'
    '"choices":[{"index":0,"delta":{"content":"läuft über das Portal."},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"askUOS-agent",'
    '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)


def _fake_askuos(captured: list[dict]) -> httpx.MockTransport:
    """An OpenAI-compatible endpoint that records each request's JSON body."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_SSE_BODY.encode()
        )

    return httpx.MockTransport(handler)


def _askuos_bot(**overrides):
    data = dict(
        id="askuos", name="askUOS", graph="passthrough",
        model={"provider": "askuos"},
        guard={"enabled": False},
        prompt={"system": ""},  # askUOS injects its own persona server-side
        graph_params={
            "locale_body_field": "language",
            "locale_values": {"de": "Deutsch", "en": "English"},
        },
    )
    data.update(overrides)
    return make_bot(**data)


def _model(captured: list[dict]):
    provider = ResolvedProvider(
        name="askuos", base_url="http://askuos.mock/v1", api_key="k",
        default_model="askUOS-agent", timeout_s=120, max_retries=0,
    )
    return build_chat_model(
        provider, http_async_client=httpx.AsyncClient(transport=_fake_askuos(captured))
    )


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


def _app(cfg, captured, sessions):
    fragment = build_passthrough_fragment(cfg, Registry(make_global(), {}), answer_model=_model(captured))
    graph = build_bot_graph(cfg, [], fragment, sessions.checkpointer)
    reg = Registry(make_global(), {cfg.id: cfg})
    return create_app(reg, sessions=sessions, graphs=_StubGraphs(graph))


async def _turn(app, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await collect(client, "askuos", body)


async def test_streams_end_to_end_and_sends_language_for_de(sessions):
    captured: list[dict] = []
    app = _app(_askuos_bot(), captured, sessions)
    events, _ = await _turn(app, {"message": "Wie bewerbe ich mich?", "client": {"locale": "de"}})

    text = "".join(e["data"]["delta"] for e in events if e["data"]["type"] == "text")
    assert text == "Die Bewerbung läuft über das Portal."
    assert events[-1]["data"]["status"] == "complete"

    # the 9a extra_body decision: `language` lands top-level in the request body
    assert captured[0]["language"] == "Deutsch"
    assert captured[0]["model"] == "askUOS-agent"
    # no system message injected (askUOS owns its persona)
    assert all(m["role"] != "system" for m in captured[0]["messages"])


async def test_language_maps_en_and_regional_variants(sessions):
    captured: list[dict] = []
    app = _app(_askuos_bot(), captured, sessions)
    await _turn(app, {"message": "How do I apply?", "client": {"locale": "en-GB"}})
    assert captured[0]["language"] == "English"  # base-language match


async def test_language_omitted_when_locale_unmapped_or_absent(sessions):
    captured: list[dict] = []
    app = _app(_askuos_bot(), captured, sessions)
    await _turn(app, {"message": "bonjour", "client": {"locale": "fr"}})
    await _turn(app, {"message": "hallo"})  # no client.locale at all
    assert "language" not in captured[0]  # unmapped → askUOS's own default (German)
    assert "language" not in captured[1]


async def test_stateless_history_grows_across_turns_within_a_session(sessions):
    captured: list[dict] = []
    app = _app(_askuos_bot(), captured, sessions)
    first, _ = await _turn(app, {"message": "Frage eins", "client": {"locale": "de"}})
    sid = first[0]["data"]["session_id"]
    await _turn(app, {"session_id": sid, "message": "Frage zwei", "client": {"locale": "de"}})

    # turn 1: [user]; turn 2: [user, assistant, user] — the gateway resends ITS history
    assert [m["role"] for m in captured[0]["messages"]] == ["user"]
    assert [m["role"] for m in captured[1]["messages"]] == ["user", "assistant", "user"]
    assert captured[1]["messages"][1]["content"] == "Die Bewerbung läuft über das Portal."


async def test_history_capped_at_history_max_turns(sessions):
    captured: list[dict] = []
    cfg = _askuos_bot(history_max_turns=1)
    app = _app(cfg, captured, sessions)
    first, _ = await _turn(app, {"message": "eins"})
    sid = first[0]["data"]["session_id"]
    await _turn(app, {"session_id": sid, "message": "zwei"})
    await _turn(app, {"session_id": sid, "message": "drei"})

    # cap = 1 turn ≈ last 2 messages; turn 3 must NOT carry the full history
    assert len(captured[2]["messages"]) == 2
    assert captured[2]["messages"][-1]["content"] == "drei"


async def test_check14_validates_locale_params():
    from .test_validation import errs

    bad = _askuos_bot(graph_params={"locale_body_field": "language", "locale_values": "Deutsch"})
    assert [e for e in errs([bad]) if "check 14" in e]
    ok = _askuos_bot()
    assert not [e for e in errs([ok]) if "check 14" in e]