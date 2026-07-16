"""In-memory session store + LangGraph checkpointer, TTL-evicted.

Single-instance, single-tenant (docs/00 §Tenancy, §Scaling ceiling). The checkpointer
is owned here and wired into the graph factory in exactly ONE place, so swapping
MemorySaver → Redis later is a one-line change (docs/04 §6).

The clock is injectable so TTL behaviour is tested deterministically without sleeping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from . import metrics


@dataclass
class Session:
    session_id: str
    bot_id: str
    created_at: float
    expires_at: float
    # Owner subject for requires_auth bots (None for anonymous/public). A session may
    # only be continued by the same subject — prevents cross-user conversation takeover
    # if a session_id leaks.
    subject: str | None = None
    # One pending interrupt per session at a time (docs/01 §Reconnection). Only the
    # correlation token is kept; the interrupt payload itself lives in the graph
    # checkpoint (each fragment re-validates its own resume via resolve_choice).
    pending_reply_to: str | None = None
    # True while a turn is streaming on this session — rejects concurrent turns
    # (docs/01: one turn at a time; interleaved checkpoint writes otherwise).
    busy: bool = False
    # Turns run on this session — observed into the session_turns histogram at
    # eviction (conversation-depth usage metric, BUILD_PLAN step 11).
    turns: int = 0


class Sessions:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._sessions: dict[str, Session] = {}
        # Wired into the graph factory only (see graphs/factory.py). Swap point.
        self.checkpointer = MemorySaver()

    def new(self, bot_id: str, ttl_s: int) -> Session:
        now = self._clock()
        sid = self._id_factory()
        s = Session(session_id=sid, bot_id=bot_id, created_at=now, expires_at=now + ttl_s)
        self._sessions[sid] = s
        return s

    def get(self, session_id: str) -> Session | None:
        s = self._sessions.get(session_id)
        if s is None:
            return None
        if self._clock() > s.expires_at:
            self._evict(session_id)
            return None
        return s

    def touch(self, session: Session, ttl_s: int) -> None:
        session.expires_at = self._clock() + ttl_s

    def expires_in(self, session: Session) -> int:
        return max(0, int(session.expires_at - self._clock()))

    def _evict(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None and session.turns > 0:
            # Conversation depth is only knowable once the session ends (step 11).
            metrics.SESSION_TURNS.labels(session.bot_id).observe(session.turns)
        deleter = getattr(self.checkpointer, "delete_thread", None)
        if callable(deleter):
            try:
                deleter(session_id)
            except Exception:  # pragma: no cover - checkpointer best-effort cleanup
                pass

    def sweep(self) -> int:
        now = self._clock()
        expired = [sid for sid, s in self._sessions.items() if now > s.expires_at]
        for sid in expired:
            self._evict(sid)
        metrics.SESSIONS_SWEPT.inc(len(expired))
        return len(expired)

    def count(self) -> int:
        return len(self._sessions)
