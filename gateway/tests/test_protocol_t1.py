"""T1 — Protocol conformance (docs/06 §T1, docs/01)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.runtime.events import HEARTBEAT_TICK, with_heartbeat


async def collect(client, bot_id, body, headers=None):
    """POST a chat turn and parse the SSE stream into (events, ping_count)."""
    events: list[dict] = []
    pings = 0
    async with client.stream(
        "POST", f"/api/v1/bots/{bot_id}/chat", json=body, headers=headers or {}
    ) as resp:
        assert resp.status_code == 200, await resp.aread()
        assert resp.headers["content-type"].startswith("text/event-stream")
        cur: dict = {}
        async for line in resp.aiter_lines():
            if line.startswith(":"):
                pings += 1
                continue
            if line == "":
                if cur:
                    events.append(cur)
                    cur = {}
                continue
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = json.loads(line[len("data:"):].strip())
    return events, pings


def seqs(events):
    return [e["data"]["seq"] for e in events]


def types(events):
    return [e["data"]["type"] for e in events]


# T1.1 — first turn with no session_id starts with `session` minting a new id
async def test_t1_1_first_turn_mints_session(client):
    events, _ = await collect(client, "echo", {"message": "hello"})
    first = events[0]["data"]
    assert first["type"] == "session"
    assert first["seq"] == 0
    assert first["session_id"]
    assert first["bot_id"] == "echo"
    assert first["protocol_version"] == "1.1"


# T1.2 — exactly one `done`; seq monotonic from 0
async def test_t1_2_one_done_seq_monotonic(client):
    events, _ = await collect(client, "echo", {"message": "hi there"})
    assert types(events).count("done") == 1
    assert seqs(events) == list(range(len(events)))
    # SSE `event:` field matches the payload type
    for e in events:
        assert e["event"] == e["data"]["type"]
    # echo streamed some text and finished complete
    assert "text" in types(events)
    assert events[-1]["data"]["type"] == "done"
    assert events[-1]["data"]["status"] == "complete"
    # deltas share one message_id and reconstruct the reply
    text_evs = [e["data"] for e in events if e["data"]["type"] == "text"]
    assert len({t["message_id"] for t in text_evs}) == 1
    assert "".join(t["delta"] for t in text_evs) == "You said: hi there"


# T1.3 — two input fields → 400 invalid_request, no stream
async def test_t1_3_multiple_inputs_rejected(client):
    resp = await client.post(
        "/api/v1/bots/echo/chat", json={"message": "hi", "choice": {"id": "x"}}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


# T1.4 — over-length → 400 message_too_long
async def test_t1_4_too_long(client):
    resp = await client.post("/api/v1/bots/echo/chat", json={"message": "x" * 4001})
    assert resp.status_code == 400
    assert resp.json()["code"] == "message_too_long"


# T1.5 — unknown bot → 404 unknown_bot
async def test_t1_5_unknown_bot(client):
    resp = await client.post("/api/v1/bots/ghost/chat", json={"message": "hi"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "unknown_bot"


# T1.6 — choice with no pending interrupt → no_pending_interrupt
async def test_t1_6_no_pending_interrupt(client):
    first, _ = await collect(client, "echo", {"message": "hello"})
    sid = first[0]["data"]["session_id"]
    events, _ = await collect(
        client, "echo", {"session_id": sid, "choice": {"id": "x"}, "reply_to": "evt_none"}
    )
    assert "no_pending_interrupt" in [e["data"].get("code") for e in events]
    assert events[-1]["data"]["type"] == "done"
    assert events[-1]["data"]["status"] == "error"


# T1.7 — heartbeat during a delayed operation
async def test_t1_7_heartbeat_on_idle():
    async def slow():
        yield {"type": "session", "seq": 0}
        await asyncio.sleep(0.12)
        yield {"type": "done", "seq": 1}

    out = [item async for item in with_heartbeat(slow(), heartbeat_s=0.03)]
    assert HEARTBEAT_TICK in out
    # real events still delivered, in order, around the ticks
    real = [x for x in out if x is not HEARTBEAT_TICK]
    assert [r["type"] for r in real] == ["session", "done"]
