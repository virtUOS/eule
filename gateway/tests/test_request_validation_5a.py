"""Batch 5a — request validation (choice shape, reply_to shape) + per-session
concurrency guard. Pre-stream 400s and the in-stream session_busy path."""

from __future__ import annotations

import asyncio

from app.runtime.runner import TurnRequest, run_turn

from .test_protocol_t1 import collect

CHAT = "/api/v1/bots/echo/chat"


# --- choice / reply_to shape (pre-stream 400) -------------------------------

async def test_reply_to_without_choice_is_400(client):
    resp = await client.post(CHAT, json={"session_id": "s", "reply_to": "evt_1"})
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_request"


async def test_message_plus_reply_to_is_400(client):
    # message would otherwise be silently discarded as a resume
    resp = await client.post(CHAT, json={"session_id": "s", "message": "hi", "reply_to": "evt_1"})
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_request"


async def test_choice_id_wrong_type_is_400(client):
    resp = await client.post(CHAT, json={"choice": {"id": {"nested": "obj"}}, "reply_to": "e"})
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_request"


async def test_choice_id_too_long_is_400(client):
    resp = await client.post(CHAT, json={"choice": {"id": "x" * 300}, "reply_to": "e"})
    assert resp.status_code == 400


async def test_choice_text_wrong_type_is_400(client):
    resp = await client.post(CHAT, json={"choice": {"id": None, "text": 123}, "reply_to": "e"})
    assert resp.status_code == 400


async def test_valid_free_text_choice_shape_passes_shape_check(client):
    # well-formed resume shape → gets past validation to the no_pending_interrupt path
    events, _ = await collect(client, "echo", {"choice": {"id": "a"}, "reply_to": "evt_x"})
    codes = [e["data"].get("code") for e in events]
    assert "no_pending_interrupt" in codes  # shape OK; nothing to resume


# --- per-session concurrency guard (in-stream session_busy) -----------------

async def test_concurrent_turn_on_same_session_rejected(registry, sessions):
    """A second turn on a session whose first turn is mid-stream gets session_busy,
    never interleaves checkpoint writes."""
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowGraph:
        async def astream(self, graph_input, config, stream_mode, subgraphs=False):
            started.set()
            await release.wait()  # hold the turn open
            return
            yield  # pragma: no cover — make this an async generator

    class _Graphs:
        def get(self, _bot_id):
            return _SlowGraph()

    session = sessions.new("echo", ttl_s=60)

    async def drive():
        return [
            ev async for ev in run_turn(
                registry, sessions, _Graphs(), "echo",
                TurnRequest(session_id=session.session_id, message="one"),
            )
        ]

    first = asyncio.ensure_future(drive())
    await started.wait()  # first turn is now streaming (busy=True)

    # second turn on the SAME session while the first holds it
    second = [
        ev async for ev in run_turn(
            registry, sessions, _Graphs(), "echo",
            TurnRequest(session_id=session.session_id, message="two"),
        )
    ]
    codes = [e.get("code") for e in second]
    assert "session_busy" in codes
    assert second[-1]["type"] == "done" and second[-1]["status"] == "error"

    release.set()
    await first
    # the busy flag is released after the first turn finishes
    assert session.busy is False
