"""In-memory session store + LangGraph checkpointer, TTL-evicted.

Single-instance, single-tenant (docs/00 §Tenancy, §Scaling ceiling). The checkpointer
is owned here and wired into the graph factory in exactly ONE place, so swapping
MemorySaver → Redis later is a one-line change (docs/04 §6).

The clock is injectable so TTL behaviour is tested deterministically without sleeping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver


@dataclass
class Session:
    session_id: str
    bot_id: str
    created_at: float
    expires_at: float
    # One pending interrupt per session at a time (docs/01 §Reconnection).
    pending_reply_to: str | None = None
    pending_interrupt: dict[str, Any] | None = field(default=None)


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
        self._sessions.pop(session_id, None)
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
        return len(expired)

    def count(self) -> int:
        return len(self._sessions)
