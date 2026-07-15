"""Protocol event construction, translation, SSE framing, heartbeat (docs/01).

The gateway runs an internal event stream; the SSE layer is a thin translator over it
(docs/02 tombstone: keep graph logic decoupled from the wire protocol).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk

PROTOCOL_VERSION = "1.1"  # 1.1: additive request `context` (docs/01 §Context)
HEARTBEAT = ": ping\n\n"


class _HeartbeatTick:
    """Sentinel yielded when the event stream is idle past the heartbeat interval."""


HEARTBEAT_TICK = _HeartbeatTick()


class EventEmitter:
    """Assigns a monotonic `seq` (from 0) to every event in one stream (docs/01)."""

    def __init__(self) -> None:
        self._seq = 0

    def make(self, type_: str, **fields: Any) -> dict[str, Any]:
        ev = {"type": type_, "seq": self._seq, **fields}
        self._seq += 1
        return ev


class MessageIds:
    """Maps a model chunk's run id to a stable, client-facing `message_id` per stream."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._n = 0

    def assign(self, raw_id: str | None) -> str:
        key = raw_id or "__none__"
        if key not in self._map:
            self._n += 1
            self._map[key] = f"m{self._n}"
        return self._map[key]


def translate(
    mode: str, data: Any, emitter: EventEmitter, msg_ids: MessageIds
) -> list[dict[str, Any]]:
    """Translate one LangGraph stream item to zero or more protocol events.

    `messages` → text; `custom` → status/sources (pass-through). Interrupts arrive on
    the `updates` channel and are handled by the runner, not here.
    """
    if mode == "messages":
        chunk, _meta = data
        # Only ASSISTANT-authored content becomes `text`. LangGraph's messages mode
        # also surfaces messages a node writes to state — e.g. the router's handoff
        # appends the user's typed reply as a HumanMessage — and user text must never
        # render as a bot bubble.
        if not isinstance(chunk, (AIMessage, AIMessageChunk)):
            return []
        content = getattr(chunk, "content", "")
        if not content:
            return []
        mid = msg_ids.assign(getattr(chunk, "id", None))
        return [emitter.make("text", message_id=mid, delta=content)]

    if mode == "custom" and isinstance(data, dict) and "type" in data:
        type_ = data["type"]
        fields = {k: v for k, v in data.items() if k != "type"}
        # A custom event's message_id (currently only `sources`) is the fragment's raw
        # internal id (e.g. the AIMessage.id it streamed text under) — route it through
        # the SAME mapping as `text` so it lands on the client as the matching bubble's
        # id, not a distinct raw id (previously a mismatch: sources bound to no bubble).
        if "message_id" in fields:
            fields["message_id"] = msg_ids.assign(fields["message_id"])
        return [emitter.make(type_, **fields)]

    return []


def format_sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event['type']}\ndata: {payload}\n\n"


async def with_heartbeat(
    events: AsyncIterator[dict[str, Any]], heartbeat_s: float
) -> AsyncIterator[Any]:
    """Yield events, injecting a HEARTBEAT_TICK sentinel whenever the upstream is idle
    longer than `heartbeat_s` (docs/01 §Transport: `: ping` every ~15s).

    The in-flight `__anext__` is driven by a persistent task that is NEVER cancelled on
    a heartbeat tick — cancelling it would propagate CancelledError into the source
    generator and kill the stream mid-turn.
    """
    it = events.__aiter__()
    pending = asyncio.ensure_future(it.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
            if not done:
                yield HEARTBEAT_TICK
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            yield item
            pending = asyncio.ensure_future(it.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
