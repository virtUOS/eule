"""In-memory fixed-window rate limiter (docs/06 §T9.2, docs/03 rate_limit).

Single-tenant, single-instance: keyed by (bot_id, client). Anonymous callers are keyed
by client IP, authenticated ones by subject. The clock is injectable for deterministic
tests. Swap for Redis alongside the checkpointer when scaling horizontally.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

_MINUTE = 60.0
_DAY = 86_400.0


@dataclass
class _Window:
    count: int
    reset_at: float


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._windows: dict[tuple[str, str], _Window] = {}

    def _roll(self, scope: str, key: str, window_s: float) -> _Window:
        now = self._clock()
        w = self._windows.get((scope, key))
        if w is None or now >= w.reset_at:
            w = _Window(count=0, reset_at=now + window_s)
            self._windows[(scope, key)] = w
        return w

    def window_count(self) -> int:
        return len(self._windows)

    def sweep(self) -> int:
        """Drop expired windows. Keys are client-mintable (per-IP), so without GC the
        map grows unboundedly; called from the app's periodic sweep task."""
        now = self._clock()
        expired = [k for k, w in self._windows.items() if now >= w.reset_at]
        for k in expired:
            del self._windows[k]
        return len(expired)

    def check(self, key: str, *, per_min: int | None, per_day: int | None) -> int | None:
        """Count this request; return retry_after seconds if a limit is exceeded, else None."""
        retry: int | None = None
        for scope, window_s, limit in (("min", _MINUTE, per_min), ("day", _DAY, per_day)):
            if limit is None:
                continue
            w = self._roll(scope, key, window_s)
            w.count += 1
            if w.count > limit:
                secs = max(1, math.ceil(w.reset_at - self._clock()))
                retry = secs if retry is None else max(retry, secs)
        return retry
