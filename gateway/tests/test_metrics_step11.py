"""BUILD_PLAN step 11 — Prometheus metrics + per-turn structured log.

Gate: /metrics exposes and parses (and is NOT under /api/); cardinality discipline
(deny-path origins never labeled raw; locales normalized); privacy (no message
content, subjects, or session ids in the exposition); turn metrics observed over the
wire; conversation depth at eviction; per-turn log line shape.
"""

from __future__ import annotations

import json
import logging

from prometheus_client import REGISTRY
from prometheus_client.parser import text_string_to_metric_families

from .test_protocol_t1 import collect

ALLOWED = "https://www.uni-osnabrueck.de"
CHAT = "/api/v1/bots/echo/chat"


def sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --- exposition ---------------------------------------------------------------

async def test_metrics_endpoint_exposes_and_parses(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    families = {f.name for f in text_string_to_metric_families(resp.text)}
    assert "chat_turns" in families or "chat_turns_total" in families
    assert "sessions_active" in families


def test_metrics_route_is_not_under_api(registry):
    """Topology protection: Caddy forwards only /api/* to the gateway, so /metrics
    must not live under /api/ or it would be internet-reachable."""
    from app.api.native import router

    paths = [r.path for r in router.routes]  # type: ignore[attr-defined]
    assert "/metrics" in paths
    assert not any(p.startswith("/api/") and "metrics" in p for p in paths)


# --- turn metrics over the wire ------------------------------------------------

async def test_turn_metrics_observed(client, caplog):
    turn_labels = {"bot": "echo", "kind": "message", "status": "complete", "origin": "none"}
    before = sample("chat_turns_total", turn_labels)
    ttft_before = sample("chat_time_to_first_text_seconds_count", {"bot": "echo"})
    dur_before = sample("chat_turn_duration_seconds_count", {"bot": "echo"})

    with caplog.at_level(logging.INFO, logger="eule.turn"):
        events, _ = await collect(client, "echo", {"message": "hello metrics"})
    assert events[-1]["data"]["status"] == "complete"

    assert sample("chat_turns_total", turn_labels) == before + 1
    assert sample("chat_time_to_first_text_seconds_count", {"bot": "echo"}) == ttft_before + 1
    assert sample("chat_turn_duration_seconds_count", {"bot": "echo"}) == dur_before + 1
    # streams gauge returned to rest
    assert sample("chat_streams_active", {"bot": "echo"}) == 0

    # per-turn structured log line: JSON with the documented shape, no content
    lines = [r.message for r in caplog.records if r.name == "eule.turn"]
    assert lines, "expected one per-turn log line"
    entry = json.loads(lines[-1])
    assert entry["bot"] == "echo" and entry["status"] == "complete"
    assert entry["kind"] == "message" and entry["duration_ms"] >= 0
    assert "hello metrics" not in lines[-1]  # never content


async def test_origin_label_allowlisted_verbatim_and_locale_normalized(client):
    labels = {"bot": "echo", "kind": "message", "status": "complete", "origin": ALLOWED}
    before = sample("chat_turns_total", labels)
    fr_before = sample("client_locales_total", {"locale": "other"})
    await collect(
        client, "echo",
        {"message": "hi", "client": {"locale": "fr-FR"}},
        headers={"origin": ALLOWED},
    )
    assert sample("chat_turns_total", labels) == before + 1
    assert sample("client_locales_total", {"locale": "other"}) == fr_before + 1


async def test_deny_path_origin_is_never_a_label(client):
    """Cardinality: a rejected Origin is attacker-mintable — it must be counted as an
    error but its raw value must not appear anywhere in the exposition."""
    before = sample("http_errors_total", {"bot": "echo", "code": "forbidden_origin"})
    resp = await client.post(
        CHAT, json={"message": "hi"},
        headers={"origin": "https://evil-attacker.example", "host": "test"},
    )
    assert resp.status_code == 403
    assert sample("http_errors_total", {"bot": "echo", "code": "forbidden_origin"}) == before + 1

    exposition = (await client.get("/metrics")).text
    assert "evil-attacker.example" not in exposition


async def test_privacy_no_content_subject_or_session_in_exposition(client):
    events, _ = await collect(client, "echo", {"message": "XYZZY-PRIVATE-CONTENT"})
    sid = events[0]["data"]["session_id"]
    exposition = (await client.get("/metrics")).text
    assert "XYZZY-PRIVATE-CONTENT" not in exposition
    assert sid not in exposition


async def test_context_and_interrupt_counters(client):
    ctx_before = sample("turns_with_context_total", {"key": "topic"})
    await collect(client, "echo", {"message": "hi", "context": {"topic": "admissions"}})
    assert sample("turns_with_context_total", {"key": "topic"}) == ctx_before + 1

    # a (rejected) resume still counts the reply kind at the endpoint
    free_before = sample("interrupt_replies_total", {"bot": "echo", "kind": "free_text"})
    await collect(client, "echo", {"choice": {"id": None, "text": "typed"}, "reply_to": "evt_x"})
    assert sample("interrupt_replies_total", {"bot": "echo", "kind": "free_text"}) == free_before + 1


# --- sessions: mint counter, depth at eviction, sweep counter -------------------

async def test_session_depth_observed_at_eviction(client, fake_clock, sessions):
    minted_before = sample("chat_sessions_total", {"bot": "echo", "auth": "anonymous"})
    depth_before = sample("session_turns_count", {"bot": "echo"})
    swept_before = sample("sessions_swept_total", {})

    first, _ = await collect(client, "echo", {"message": "one"})
    sid = first[0]["data"]["session_id"]
    await collect(client, "echo", {"session_id": sid, "message": "two"})

    assert sample("chat_sessions_total", {"bot": "echo", "auth": "anonymous"}) == minted_before + 1

    fake_clock.advance(7201)
    assert sessions.sweep() == 1
    assert sample("session_turns_count", {"bot": "echo"}) == depth_before + 1
    assert sample("session_turns_sum", {"bot": "echo"}) >= 2  # two turns on that session
    assert sample("sessions_swept_total", {}) == swept_before + 1


async def test_store_gauges_reflect_counts(client, sessions):
    await collect(client, "echo", {"message": "hi"})
    assert sample("sessions_active", {}) == float(sessions.count())


# --- mcp + guard counters --------------------------------------------------------

async def test_mcp_call_counters(sessions):
    from app.mcp.client import mcp_call
    from app.runtime.context import ANONYMOUS, RuntimeContext

    from .conftest import make_bot
    from .test_mcp_t4 import _FakeMcpClient

    cfg = make_bot()
    ctx = RuntimeContext(
        bot_id=cfg.id, config=cfg, identity=ANONYMOUS, session_id="s", request_id="r", locale=None
    )
    ok_before = sample("mcp_calls_total", {"tool": "t_metrics", "outcome": "ok"})
    dur_before = sample("mcp_call_duration_seconds_count", {"tool": "t_metrics"})
    await mcp_call(ctx, _FakeMcpClient(), "t_metrics", {"q": "x"})
    assert sample("mcp_calls_total", {"tool": "t_metrics", "outcome": "ok"}) == ok_before + 1
    assert sample("mcp_call_duration_seconds_count", {"tool": "t_metrics"}) == dur_before + 1


async def test_guard_verdict_counter(sessions):
    from langchain_core.messages import AIMessage
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from .conftest import make_bot
    from .test_guard_classifier import _run

    cfg = make_bot(id="echo", guard={"enabled": True, "provider": "default"})
    before = sample("guard_verdicts_total", {"bot": "echo", "verdict": "out_of_scope"})
    guard = GenericFakeChatModel(messages=iter([AIMessage(content="out_of_scope")]))
    await _run(cfg, guard, sessions, "off topic?")
    assert sample("guard_verdicts_total", {"bot": "echo", "verdict": "out_of_scope"}) == before + 1
