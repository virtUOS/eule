"""The uniform gateway driving loop (docs/04 §8). Produces an internal stream of
protocol event dicts; SSE framing + heartbeat are applied by the endpoint."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ..registry.registry import Registry
from . import metrics
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


def _fail(
    emitter: EventEmitter, sessions: Sessions, session: Session, code: str, message: str,
    *, recoverable: bool = False,
) -> Iterator[dict[str, Any]]:
    """The error + terminal-done epilogue, emitted on every early-exit path."""
    yield emitter.make("error", code=code, message=message, recoverable=recoverable)
    yield emitter.make(
        "done", status="error", session_id=session.session_id,
        expires_in=sessions.expires_in(session),
    )


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

    auth_label = "authenticated" if req.identity.authenticated else "anonymous"

    # --- session resolution ---
    session: Session
    if req.session_id is None:
        session = sessions.new(bot_id, cfg.session_ttl_s)
        session.subject = req.identity.subject  # stamp owner (None for public bots)
        metrics.SESSIONS_TOTAL.labels(bot_id, auth_label).inc()
    else:
        found = sessions.get(req.session_id)
        # A session may only be continued by the subject that created it, AND only on
        # the bot that created it — all bots share one checkpointer keyed by session_id,
        # so without the bot check a session id minted on bot A would resume A's
        # checkpoint (messages, scratch, pending interrupt) inside bot B's graph,
        # crossing scope boundaries structurally (golden rule 3). Either mismatch is
        # treated as not-found (fail-safe, no info leak that the session exists).
        if found is not None and (found.subject != req.identity.subject or found.bot_id != bot_id):
            found = None
        if found is None:
            # Unknown/expired session → mint a fresh one, then fail this turn so the
            # widget starts over cleanly (docs/01: session_not_found, start fresh).
            fresh = sessions.new(bot_id, cfg.session_ttl_s)
            metrics.SESSIONS_TOTAL.labels(bot_id, auth_label).inc()
            yield emitter.make(
                "session",
                session_id=fresh.session_id,
                protocol_version=PROTOCOL_VERSION,
                bot_id=bot_id,
                expires_in=sessions.expires_in(fresh),
            )
            for ev in _fail(
                emitter, sessions, fresh, "session_not_found",
                "Your session expired. Starting a new conversation.",
            ):
                yield ev
            return
        session = found

    yield emitter.make(
        "session",
        session_id=session.session_id,
        protocol_version=PROTOCOL_VERSION,
        bot_id=bot_id,
        expires_in=sessions.expires_in(session),
    )

    # One turn at a time per session. Concurrent turns would interleave checkpoint
    # writes on the same thread_id and race the pending-interrupt state. The
    # check-and-set is atomic (single event loop, no await between them).
    if session.busy:
        for ev in _fail(
            emitter, sessions, session, "session_busy",
            "This conversation is already processing a message. Please wait.",
            recoverable=True,
        ):
            yield ev
        return
    session.busy = True
    session.turns += 1  # conversation depth, observed at eviction (step 11)
    try:
        is_resume = req.choice is not None or req.reply_to is not None

        if is_resume:
            if session.pending_reply_to is None or session.pending_reply_to != req.reply_to:
                for ev in _fail(
                    emitter, sessions, session, "no_pending_interrupt",
                    "There is nothing to resume; please start a new message.",
                ):
                    yield ev
                return
            graph_input: Any = Command(resume=_normalized_resume(req))
            session.pending_reply_to = None
        else:
            # A fresh message abandons any prior interrupt: clear pending so a stale/
            # replayed reply_to can no longer resume it (docs/01 §Reconnection — "fails
            # safe, no double execution"). Without this, a desynced client (e.g. after a
            # reload) could resume an interrupt the user already walked away from.
            session.pending_reply_to = None
            graph_input = _initial_state(req)

        async for ev in _run_graph(
            registry, sessions, graphs, bot_id, cfg, session, req, emitter, msg_ids, graph_input
        ):
            yield ev
    finally:
        session.busy = False


async def _run_graph(  # noqa: PLR0913 — threads the resolved turn state into the graph loop
    registry: Registry,
    sessions: Sessions,
    graphs: Any,
    bot_id: str,
    cfg: Any,
    session: Session,
    req: TurnRequest,
    emitter: EventEmitter,
    msg_ids: MessageIds,
    graph_input: Any,
) -> AsyncIterator[dict[str, Any]]:
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
        # subgraphs=True: WITHOUT it, `custom` events (status/sources via
        # get_stream_writer) emitted inside a routed sub-bot's subgraph are silently
        # dropped — only top-level nodes' events surface. With it, each item is a
        # (namespace, mode, data) triple; the namespace is irrelevant to translation.
        async for _ns, mode, data in graph.astream(
            graph_input, config=config,
            stream_mode=["messages", "custom", "updates"],
            subgraphs=True,
        ):
            if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                # A subgraph interrupt can surface once per namespace level; the
                # payload is the same interrupt — keep the first (one pending per
                # session, docs/01).
                if pending is None:
                    pending = data["__interrupt__"][0]
                continue
            for ev in translate(mode, data, emitter, msg_ids):
                yield ev
    except Exception:  # noqa: BLE001 — surface as protocol error, never leak a stack
        # Log the full cause server-side (MCP unreachable, auth failure, tool not found,
        # model error…) — the user only ever sees the generic line below, so without
        # this the real fault is invisible in the logs.
        logging.getLogger("eule.runner").exception(
            "turn failed for bot=%s session=%s", cfg.id, session.session_id
        )
        for ev in _fail(
            emitter, sessions, session, "internal_error",
            "Something went wrong. Please try again.",
        ):
            yield ev
        return

    sessions.touch(session, cfg.session_ttl_s)

    if pending is not None:
        reply_to = f"evt_{uuid4().hex[:8]}"
        value = dict(pending.value)
        session.pending_reply_to = reply_to
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
