"""The uniform gateway driving loop (docs/04 §8). Produces an internal stream of
protocol event dicts; SSE framing + heartbeat are applied by the endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ..registry.registry import Registry
from .context import ANONYMOUS, Identity, build_runtime_context
from .events import PROTOCOL_VERSION, EventEmitter, MessageIds, translate
from .sessions import Session, Sessions


@dataclass
class TurnRequest:
    session_id: str | None = None
    message: str | None = None
    choice: dict[str, Any] | None = None  # {"id": str|None, "text": str|None}
    reply_to: str | None = None
    greeting: bool = False
    locale: str | None = None
    # Host-page passthrough, allowlist-validated pre-stream by the endpoint
    # (docs/01 §Context). UNTRUSTED data: flows only into turn_input, never identity.
    context: dict[str, Any] | None = None
    # Trusted identity, resolved pre-stream by the endpoint (ANONYMOUS for public bots).
    identity: Identity = ANONYMOUS


def _initial_state(req: TurnRequest) -> dict[str, Any]:
    if req.greeting and req.message is None:
        turn_input: dict[str, Any] = {"kind": "greeting"}
    else:
        turn_input = {"kind": "text", "text": req.message or ""}
    if req.context is not None:
        turn_input["context"] = req.context  # untrusted host-page data (docs/04 §5)
    messages = [] if turn_input["kind"] == "greeting" else [HumanMessage(content=turn_input["text"])]
    return {"messages": messages, "turn_input": turn_input, "scratch": {}}


def _normalized_resume(req: TurnRequest) -> dict[str, Any]:
    choice = req.choice or {}
    return {"kind": "choice", "id": choice.get("id"), "text": choice.get("text")}


async def run_turn(
    registry: Registry,
    sessions: Sessions,
    graphs: Any,
    bot_id: str,
    req: TurnRequest,
) -> AsyncIterator[dict[str, Any]]:
    emitter = EventEmitter()
    msg_ids = MessageIds()
    cfg = registry.get(bot_id)  # pre-checked by endpoint; UnknownBot → 404 there

    # --- session resolution ---
    session: Session
    if req.session_id is None:
        session = sessions.new(bot_id, cfg.session_ttl_s)
        session.subject = req.identity.subject  # stamp owner (None for public bots)
    else:
        found = sessions.get(req.session_id)
        # A session may only be continued by the subject that created it. A mismatch is
        # treated as not-found (fail-safe, no info leak that the session exists).
        if found is not None and found.subject != req.identity.subject:
            found = None
        if found is None:
            # Unknown/expired session → mint a fresh one, then fail this turn so the
            # widget starts over cleanly (docs/01: session_not_found, start fresh).
            fresh = sessions.new(bot_id, cfg.session_ttl_s)
            yield emitter.make(
                "session",
                session_id=fresh.session_id,
                protocol_version=PROTOCOL_VERSION,
                bot_id=bot_id,
                expires_in=sessions.expires_in(fresh),
            )
            yield emitter.make(
                "error",
                code="session_not_found",
                message="Your session expired. Starting a new conversation.",
                recoverable=False,
            )
            yield emitter.make(
                "done", status="error", session_id=fresh.session_id,
                expires_in=sessions.expires_in(fresh),
            )
            return
        session = found

    yield emitter.make(
        "session",
        session_id=session.session_id,
        protocol_version=PROTOCOL_VERSION,
        bot_id=bot_id,
        expires_in=sessions.expires_in(session),
    )

    is_resume = req.choice is not None or req.reply_to is not None

    if is_resume:
        if session.pending_reply_to is None or session.pending_reply_to != req.reply_to:
            yield emitter.make(
                "error",
                code="no_pending_interrupt",
                message="There is nothing to resume; please start a new message.",
                recoverable=False,
            )
            yield emitter.make(
                "done", status="error", session_id=session.session_id,
                expires_in=sessions.expires_in(session),
            )
            return
        graph_input: Any = Command(resume=_normalized_resume(req))
        session.pending_reply_to = None
        session.pending_interrupt = None
    else:
        # A fresh message abandons any prior interrupt: clear the pending state so a
        # stale/replayed reply_to can no longer resume it (docs/01 §Reconnection —
        # "fails safe, no double execution"). Without this, a desynced client (e.g.
        # after a reload) could later resume an interrupt the user already walked away from.
        session.pending_reply_to = None
        session.pending_interrupt = None
        graph_input = _initial_state(req)

    ctx = build_runtime_context(
        cfg,
        session_id=session.session_id,
        request_id=uuid4().hex,
        locale=req.locale,
        identity=req.identity,
    )
    graph = graphs.get(bot_id)
    config = {"configurable": {"ctx": ctx, "thread_id": session.session_id}}

    pending: Any = None
    try:
        async for mode, data in graph.astream(
            graph_input, config=config, stream_mode=["messages", "custom", "updates"]
        ):
            if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                pending = data["__interrupt__"][0]
                continue
            for ev in translate(mode, data, emitter, msg_ids):
                yield ev
    except Exception:  # noqa: BLE001 — surface as protocol error, never leak a stack
        yield emitter.make(
            "error", code="internal_error",
            message="Something went wrong. Please try again.", recoverable=False,
        )
        yield emitter.make(
            "done", status="error", session_id=session.session_id,
            expires_in=sessions.expires_in(session),
        )
        return

    sessions.touch(session, cfg.session_ttl_s)

    if pending is not None:
        reply_to = f"evt_{uuid4().hex[:8]}"
        value = dict(pending.value)
        session.pending_reply_to = reply_to
        session.pending_interrupt = value
        yield emitter.make(
            "quick_replies",
            reply_to=reply_to,
            prompt=value.get("prompt", ""),
            options=value.get("options", []),
            allow_free_text=value.get("allow_free_text", True),
        )
        yield emitter.make(
            "done", status="awaiting_input", session_id=session.session_id,
            expires_in=sessions.expires_in(session),
        )
    else:
        yield emitter.make(
            "done", status="complete", session_id=session.session_id,
            expires_in=sessions.expires_in(session),
        )
