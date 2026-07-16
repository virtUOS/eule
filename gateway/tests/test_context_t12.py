"""T12 — Host-page context passthrough (docs/01 §Context, docs/04 §5).

Security posture (extends T3): `context` is attacker-controllable host-page data.
It must (a) be strictly allowlist-validated pre-stream, (b) reach the graph only as
`turn_input.context`, and (c) never touch RuntimeContext/identity.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.runtime.context import ANONYMOUS
from app.runtime.runner import TurnRequest, _initial_state, run_turn

from .test_protocol_t1 import collect


# --- T12.1 — wire validation: strict allowlist, pre-stream 400s ---------------

async def _post(client, body):
    return await client.post("/api/v1/bots/echo/chat", json=body)


async def test_t12_1a_unknown_key_rejected(client):
    resp = await _post(client, {"message": "hi", "context": {"page": "x", "evil": "y"}})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    assert "evil" in resp.json()["message"]


async def test_t12_1b_identity_shaped_keys_are_unknown_keys(client):
    # There is no privileged spelling: subject/claims/roles are simply not allowlisted.
    for key in ("subject", "claims", "roles", "identity"):
        resp = await _post(client, {"message": "hi", "context": {key: "attacker"}})
        assert resp.status_code == 400, key
        assert resp.json()["code"] == "invalid_request"


async def test_t12_1c_oversize_value_rejected(client):
    resp = await _post(client, {"message": "hi", "context": {"page": "x" * 2001}})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    resp = await _post(client, {"message": "hi", "context": {"topic": "x" * 201}})
    assert resp.status_code == 400


async def test_t12_1d_non_string_value_rejected(client):
    for bad in ({"page": 5}, {"topic": {"nested": "x"}}, {"locale": ["de"]}):
        resp = await _post(client, {"message": "hi", "context": bad})
        assert resp.status_code == 400, bad
        assert resp.json()["code"] == "invalid_request"


async def test_t12_1e_valid_context_accepted_over_wire(client):
    body = {"message": "hello", "context": {"page": "https://uni.example/informatik", "topic": "admissions"}}
    events, _ = await collect(client, "echo", body)
    assert events[-1]["data"]["status"] == "complete"


async def test_t12_1f_context_without_input_field_still_invalid(client):
    # context is metadata, not an input: the exactly-one-input rule is unaffected.
    resp = await _post(client, {"context": {"topic": "admissions"}})
    assert resp.status_code == 400


# --- T12.2 — context reaches the graph as turn_input data ---------------------

def test_t12_2a_initial_state_carries_context_on_text_turn():
    req = TurnRequest(message="hi", context={"page": "https://x", "topic": "t"})
    state = _initial_state(req)
    assert state["turn_input"]["context"] == {"page": "https://x", "topic": "t"}
    assert state["turn_input"]["kind"] == "text"


def test_t12_2b_initial_state_carries_context_on_greeting_turn():
    req = TurnRequest(greeting=True, context={"topic": "t"})
    state = _initial_state(req)
    assert state["turn_input"] == {"kind": "greeting", "context": {"topic": "t"}}
    assert state["messages"] == []


def test_t12_2c_absent_context_leaves_turn_input_unchanged():
    state = _initial_state(TurnRequest(message="hi"))
    assert "context" not in state["turn_input"]


# --- T12.3 — isolation: context never touches identity/RuntimeContext ---------

class _CaptureGraph:
    """Stub graph capturing exactly what the runner hands to astream."""

    def __init__(self) -> None:
        self.inputs: list[Any] = []
        self.configs: list[dict[str, Any]] = []

    async def astream(
        self, graph_input: Any, config: dict[str, Any], stream_mode: Any, subgraphs: bool = False
    ):
        self.inputs.append(graph_input)
        self.configs.append(config)
        if False:  # pragma: no cover — make this an async generator
            yield None


class _CaptureCache:
    def __init__(self, graph: _CaptureGraph) -> None:
        self._graph = graph

    def get(self, bot_id: str) -> _CaptureGraph:
        return self._graph


async def _drain(gen):
    return [ev async for ev in gen]


async def test_t12_3_context_flows_to_turn_input_only_never_identity(registry, sessions):
    graph = _CaptureGraph()
    req = TurnRequest(message="hi", context={"page": "https://x", "topic": "t"})
    await _drain(run_turn(registry, sessions, _CaptureCache(graph), "echo", req))

    [graph_input] = graph.inputs
    [config] = graph.configs
    assert graph_input["turn_input"]["context"] == {"page": "https://x", "topic": "t"}

    ctx = config["configurable"]["ctx"]
    # identity is exactly the trusted one resolved pre-stream — untouched by context
    assert ctx.identity is ANONYMOUS
    assert not ctx.identity.authenticated
    assert ctx.identity.subject is None
    # and nothing context-shaped leaked onto the runtime context or its claims
    assert ctx.identity.claims == {}


async def test_t12_3b_resume_turn_never_delivers_context(registry, sessions):
    from langgraph.types import Command

    graph = _CaptureGraph()
    cache = _CaptureCache(graph)

    # establish a session with a pending interrupt
    session = sessions.new("echo", ttl_s=60)
    session.pending_reply_to = "evt_x"
    session.pending_interrupt = {"prompt": "?", "options": []}

    req = TurnRequest(
        session_id=session.session_id,
        choice={"id": "a"},
        reply_to="evt_x",
        context={"topic": "smuggled"},  # validated but must NOT ride the resume
    )
    await _drain(run_turn(registry, sessions, cache, "echo", req))

    [graph_input] = graph.inputs
    assert isinstance(graph_input, Command)
    assert graph_input.resume == {"kind": "choice", "id": "a", "text": None}
    assert "context" not in graph_input.resume
