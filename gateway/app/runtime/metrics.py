"""Prometheus metrics + per-turn structured log (BUILD_PLAN step 11).

Two hard rules (docs/BUILD_PLAN.md step 11):
- CARDINALITY: label values come only from CLOSED sets — bot ids (registry), protocol
  error codes, tool allowlists, done statuses, guard verdicts, normalized locales, and
  origins normalized against the bot's embed allowlist. NEVER session ids, subjects,
  raw URLs, or free text.
- PRIVACY: counts and durations only. No message content, no per-user traceability.
  The per-turn log line carries context.page (opt-in host-page attribution, step 8)
  but never conversation content.

All metrics live on the default registry, defined once at import (so repeated
create_app calls in tests never re-register). Store gauges are bound per app via
`bind_store_gauges` (last-created app wins — correct for both prod and tests).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

turn_logger = logging.getLogger("eule.turn")

_TURN_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 45, 90, 180)
_TTFT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30)
_CALL_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 15, 60)
# Fibonacci-ish depth buckets: 1-turn sessions (hit-and-run) up to long conversations.
_DEPTH_BUCKETS = (1, 2, 3, 5, 8, 13, 21, 34)

# --- operational -------------------------------------------------------------

TURNS = Counter(
    "chat_turns_total", "Chat turns by bot, input kind, terminal status, embed origin",
    ["bot", "kind", "status", "origin"],
)
TURN_DURATION = Histogram(
    "chat_turn_duration_seconds", "End-to-end turn duration", ["bot"], buckets=_TURN_BUCKETS
)
TTFT = Histogram(
    "chat_time_to_first_text_seconds",
    "Turn start to first text event (perceived latency: guard + tools + model TTFT)",
    ["bot"], buckets=_TTFT_BUCKETS,
)
STREAMS_ACTIVE = Gauge("chat_streams_active", "Currently streaming turns", ["bot"])
MODEL_CALL_DURATION = Histogram(
    "model_call_duration_seconds", "Provider model-call duration", ["model"], buckets=_CALL_BUCKETS
)
MCP_CALLS = Counter("mcp_calls_total", "MCP tool calls", ["tool", "outcome"])
MCP_CALL_DURATION = Histogram(
    "mcp_call_duration_seconds", "MCP tool-call duration", ["tool"], buckets=_CALL_BUCKETS
)
ERRORS = Counter(
    "http_errors_total", "Protocol errors (pre-stream HTTP + in-stream)", ["bot", "code"]
)
SESSIONS_ACTIVE = Gauge("sessions_active", "Live sessions in the in-memory store")
RATELIMIT_WINDOWS = Gauge("ratelimit_windows", "Live rate-limit windows")
SESSIONS_SWEPT = Counter("sessions_swept_total", "Sessions evicted by the periodic sweep")
AUTH_VERIFICATIONS = Counter(
    "auth_verifications_total", "Bearer-token verifications", ["outcome"]
)

# --- usage insights ----------------------------------------------------------

SESSIONS_TOTAL = Counter("chat_sessions_total", "Sessions minted", ["bot", "auth"])
SESSION_TURNS = Histogram(
    "session_turns", "Turns per session, observed at eviction", ["bot"], buckets=_DEPTH_BUCKETS
)
GUARD_VERDICTS = Counter("guard_verdicts_total", "Guard scope verdicts", ["bot", "verdict"])
ROUTER_CHOICES = Counter(
    "router_choices_total",
    "Front-door routing decisions (incl. the __menu__ escape) by method",
    ["router_bot", "target", "method"],  # method: menu | classifier | context
)
ROUTER_CLASSIFIER = Counter(
    "router_classifier_outcomes_total",
    "Classifier-routing outcomes (step 12); the non-routed share = menu-fallback rate",
    ["router_bot", "outcome"],  # routed | none | unparseable | error
)
INTERRUPT_REPLIES = Counter(
    "interrupt_replies_total", "Interrupt resumes by reply kind", ["bot", "kind"]
)
TURNS_WITH_CONTEXT = Counter(
    "turns_with_context_total", "Turns carrying a host-page context key", ["key"]
)
SOURCES_EMITTED = Counter("sources_emitted_total", "Sources events emitted", ["bot"])
CLIENT_LOCALES = Counter("client_locales_total", "Turns by client locale", ["locale"])


# --- normalizers (the cardinality gate) --------------------------------------

def normalize_origin(origin: str | None, host: str | None, allowed: list[str]) -> str:
    """Closed-set origin label. An allowlisted origin passes verbatim (config-bounded);
    the deny path NEVER labels the raw header — those values are attacker-mintable."""
    if origin is None:
        return "none"
    if origin in allowed:
        return origin
    from urllib.parse import urlparse

    if host is not None and urlparse(origin).netloc.lower() == host.lower():
        return "same-origin"
    return "other"


def normalize_locale(locale: str | None) -> str:
    base = (locale or "").split("-")[0].lower()
    return base if base in ("de", "en") else "other"


def bind_store_gauges(sessions: Any, ratelimiter: Any) -> None:
    SESSIONS_ACTIVE.set_function(lambda: float(sessions.count()))
    RATELIMIT_WINDOWS.set_function(lambda: float(ratelimiter.window_count()))


def exposition() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


# --- the turn observer --------------------------------------------------------

async def observe_turn(
    bot_id: str,
    origin_label: str,
    kind: str,
    context_page: str | None,
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Pass-through wrapper over the internal event stream: one choke point sees every
    event, so turn counters/durations/TTFT/sources/errors and the per-turn log line all
    derive here without touching the runner."""
    start = time.perf_counter()
    ttft: float | None = None
    status = "transport_drop"  # overwritten by the terminal done; kept if the client vanishes
    error_code: str | None = None
    STREAMS_ACTIVE.labels(bot_id).inc()
    try:
        async for ev in events:
            ev_type = ev.get("type")
            if ev_type == "text" and ttft is None:
                ttft = time.perf_counter() - start
                TTFT.labels(bot_id).observe(ttft)
            elif ev_type == "sources":
                SOURCES_EMITTED.labels(bot_id).inc()
            elif ev_type == "error":
                error_code = str(ev.get("code", "unknown"))
                ERRORS.labels(bot_id, error_code).inc()
            elif ev_type == "done":
                status = str(ev.get("status", "unknown"))
            yield ev
    finally:
        STREAMS_ACTIVE.labels(bot_id).dec()
        duration = time.perf_counter() - start
        TURNS.labels(bot_id, kind, status, origin_label).inc()
        TURN_DURATION.labels(bot_id).observe(duration)
        # One structured line per turn — counts/durations/attribution, never content.
        turn_logger.info(
            json.dumps(
                {
                    "bot": bot_id,
                    "origin": origin_label,
                    "context_page": context_page,
                    "kind": kind,
                    "status": status,
                    "error_code": error_code,
                    "duration_ms": round(duration * 1000),
                    "ttft_ms": round(ttft * 1000) if ttft is not None else None,
                },
                separators=(",", ":"),
            )
        )
