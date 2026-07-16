"""Native wire-protocol endpoints (docs/01):
  POST    /api/v1/bots/{id}/chat    — one request → one SSE stream.
  OPTIONS /api/v1/bots/{id}/chat    — CORS preflight.
  GET     /api/v1/bots/{id}/config  — widget bootstrap (CORS-checked, ETag).

Embedding/abuse controls (docs/06 §T9): the Origin is checked against the bot's
`embedding.allowed_origins` on both endpoints, cross-origin responses carry the
matching CORS headers, and requests are rate-limited per (bot, client).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from urllib.parse import urlparse
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..auth.keycloak import AuthError, bearer_token
from ..registry.models import BotCfg
from ..registry.registry import UnknownBot
from ..runtime.context import ANONYMOUS, Identity
from ..runtime.events import HEARTBEAT, HEARTBEAT_TICK, format_sse, with_heartbeat
from ..runtime.runner import TurnRequest, run_turn

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    # Internal liveness/readiness probe (container + reverse-proxy healthchecks). Not
    # public-facing: no auth, no origin gate. Reaching it means config validated + booted.
    return JSONResponse({"status": "ok", "bots": request.app.state.registry.ids()})


_CORS_METHODS = "POST, GET, OPTIONS"
_CORS_HEADERS = "authorization, content-type"


class ClientInfo(BaseModel):
    model_config = ConfigDict(extra="allow")  # forward-compatible; unknown fields ignored
    locale: str | None = None


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = None
    message: str | None = None
    choice: dict[str, Any] | None = None
    reply_to: str | None = None
    greeting: bool = False
    client: ClientInfo | None = None
    context: dict[str, Any] | None = None  # host-page passthrough (docs/01 §Context)


# docs/01 §Context: strict key allowlist + per-key size caps. `context` crosses a
# trust boundary (attacker-controllable host-page data), so unlike server→client
# events it is validated strictly — it must not become a smuggling channel.
_CONTEXT_CAPS: dict[str, int] = {"page": 2000, "topic": 200, "locale": 35}


def _context_error(context: dict[str, Any] | None) -> str | None:
    """User-facing validation error, or None when the context is acceptable."""
    if context is None:
        return None
    for key, value in context.items():
        cap = _CONTEXT_CAPS.get(key)
        if cap is None:
            return f"Unknown context key '{key}'."
        if not isinstance(value, str):
            return f"context.{key} must be a string."
        if len(value) > cap:
            return f"context.{key} exceeds the {cap}-character limit."
    return None


def _error_response(
    status: int,
    code: str,
    message: str,
    recoverable: bool = False,
    *,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # Pre-stream errors mirror the SSE error shape minus framing (docs/01 §Error codes).
    body: dict[str, Any] = {"type": "error", "code": code, "message": message, "recoverable": recoverable}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, headers=headers or {})


def _cors_headers(origin: str | None, cfg: BotCfg, host: str | None) -> tuple[bool, dict[str, str]]:
    """(allowed, headers). No Origin = non-browser → allowed, no headers. TRUE
    same-origin is also allowed without allowlisting: browsers send Origin on every
    POST including same-origin ones, so the deployment's own pages (standalone page,
    demo host) would otherwise 403 on /chat unless they allowlisted themselves — a
    deployment trap (config GETs succeeded, every message failed). Host-only
    comparison: behind the TLS-terminating proxy the gateway sees http, so a scheme
    check would wrongly reject https origins; same-host-different-scheme is not a
    boundary we can enforce here. A cross-origin request is allowed only when its
    Origin is in the bot's allowlist."""
    if origin is None:
        return True, {}
    origin_host = urlparse(origin).netloc
    if host is not None and origin_host and origin_host.lower() == host.lower():
        return True, {}  # same-origin: no CORS headers needed
    if origin in cfg.embedding.allowed_origins:
        return True, {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return False, {}


def _client_ip(request: Request, trust_forwarded_for: bool) -> str:
    """Rate-limit key source. X-Forwarded-For is client-forgeable, so it is honored
    ONLY when config says a trusted proxy fronts the gateway — and then the RIGHTMOST
    entry is used (the hop appended by OUR proxy); the leftmost entries are whatever
    the client sent and would allow limit bypass / victim-budget exhaustion."""
    if trust_forwarded_for:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@router.options("/api/v1/bots/{bot_id}/chat")
async def chat_preflight(bot_id: str, request: Request) -> Response:
    try:
        cfg = request.app.state.registry.get(bot_id)
    except UnknownBot:
        return Response(status_code=404)
    _allowed, cors = _cors_headers(request.headers.get("origin"), cfg, request.headers.get("host"))
    if cors:
        cors = {
            **cors,
            "Access-Control-Allow-Methods": _CORS_METHODS,
            "Access-Control-Allow-Headers": _CORS_HEADERS,
            "Access-Control-Max-Age": "600",
        }
    return Response(status_code=204, headers=cors)


@router.post("/api/v1/bots/{bot_id}/chat")
async def chat(bot_id: str, body: ChatBody, request: Request) -> Any:
    registry = request.app.state.registry
    sessions = request.app.state.sessions
    graphs = request.app.state.graphs
    ratelimiter = request.app.state.ratelimiter
    heartbeat_s = registry.global_cfg.streaming.heartbeat_s

    # unknown bot → 404 (pre-stream; no CORS headers — bot/allowlist unknown)
    try:
        cfg = registry.get(bot_id)
    except UnknownBot:
        return _error_response(404, "unknown_bot", f"No bot with id '{bot_id}'.")

    # Origin gate (docs/06 T9.1). A disallowed cross-origin embed is refused outright.
    origin = request.headers.get("origin")
    allowed, cors = _cors_headers(origin, cfg, request.headers.get("host"))
    if not allowed:
        return _error_response(403, "forbidden_origin", "This origin may not embed this bot.")

    # exactly one input field (message | choice | greeting:true) — docs/01 §Request
    inputs = sum(x is not None for x in (body.message, body.choice)) + (1 if body.greeting else 0)
    if inputs != 1:
        return _error_response(
            400, "invalid_request", "Provide exactly one of: message, choice, greeting.",
            headers=cors,
        )

    # Context passthrough (docs/01 §Context): strict allowlist, pre-stream.
    ctx_err = _context_error(body.context)
    if ctx_err is not None:
        return _error_response(400, "invalid_request", ctx_err, headers=cors)

    # Enforce the per-bot char limit on any free text the user can type — a plain
    # message OR a free-text reply to a quick-reply interrupt (choice.text).
    choice_text = body.choice.get("text") if body.choice else None
    longest = max((len(t) for t in (body.message, choice_text) if isinstance(t, str)), default=0)
    if longest > cfg.max_message_chars:
        return _error_response(
            400, "message_too_long",
            f"Message exceeds the {cfg.max_message_chars}-character limit.", headers=cors,
        )

    # Auth PRE-STREAM (docs/01: unauthorized/token_expired 401, forbidden 403) so no
    # graph runs unauthenticated. Identity is injected out-of-band.
    identity: Identity = ANONYMOUS
    if cfg.requires_auth:
        verifier = getattr(request.app.state, "auth", None)
        if verifier is None:
            return _error_response(500, "internal_error", "Auth is not configured.", headers=cors)
        token = bearer_token(request.headers.get("authorization"))
        if token is None:
            return _error_response(401, "unauthorized", "Authentication required.", headers=cors)
        try:
            assert cfg.identity is not None  # guaranteed by validation check 5
            # Off the event loop: on a cold cache / key rotation, verify() does a
            # synchronous JWKS HTTP fetch — inline it would stall EVERY stream for
            # every bot while a slow/hung IdP times out.
            identity = await asyncio.to_thread(verifier.verify, token, cfg.identity)
        except AuthError as e:
            return _error_response(e.status, e.code, e.message, recoverable=e.recoverable, headers=cors)

    # Rate limit (docs/06 T9.2): tier + key by identity (subject) or client IP.
    if identity.authenticated:
        tier = cfg.rate_limit.authenticated
        rl_key = f"{bot_id}:sub:{identity.subject}"
    else:
        tier = cfg.rate_limit.anonymous
        trust_xff = registry.global_cfg.network.trust_forwarded_for
        rl_key = f"{bot_id}:ip:{_client_ip(request, trust_xff)}"
    if tier is not None:
        retry_after = ratelimiter.check(
            rl_key, per_min=tier.requests_per_min, per_day=tier.requests_per_day
        )
        if retry_after is not None:
            return _error_response(
                429, "rate_limited", "Too many requests. Please slow down.",
                recoverable=True, extra={"retry_after": retry_after}, headers=cors,
            )

    turn = TurnRequest(
        session_id=body.session_id,
        message=body.message,
        choice=body.choice,
        reply_to=body.reply_to,
        greeting=body.greeting,
        locale=(body.client.locale if body.client else None),
        context=body.context,
        identity=identity,
    )

    async def stream() -> Any:
        events = run_turn(registry, sessions, graphs, bot_id, turn)
        async for item in with_heartbeat(events, heartbeat_s):
            if item is HEARTBEAT_TICK:
                yield HEARTBEAT
            else:
                yield format_sse(item)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", **cors},
    )


@router.get("/api/v1/bots/{bot_id}/config")
async def bootstrap(bot_id: str, request: Request, lang: str = "de") -> Any:
    registry = request.app.state.registry
    try:
        cfg = registry.get(bot_id)
    except UnknownBot:
        return _error_response(404, "unknown_bot", f"No bot with id '{bot_id}'.")

    origin = request.headers.get("origin")
    allowed, cors = _cors_headers(origin, cfg, request.headers.get("host"))
    if not allowed:
        return _error_response(403, "forbidden_origin", "This origin may not embed this bot.")

    theme = registry.resolve_theme(cfg)
    payload = {
        "name": cfg.name,
        "theme": {
            "light": theme.light,
            "dark": theme.dark,
            "dark_mode": theme.dark_mode,
            "radius": theme.radius,
        },
        "starter_replies": [sr.model_dump() for sr in cfg.starter_replies.get(lang, [])],
        "greeting": {"mode": cfg.greeting.mode},
    }

    body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    etag = '"' + hashlib.sha256(body_bytes).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=300", **cors}

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=payload, headers=headers)
