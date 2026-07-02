"""Native wire-protocol endpoints (docs/01):
  POST /api/v1/bots/{id}/chat    — one request → one SSE stream.
  GET  /api/v1/bots/{id}/config  — widget bootstrap (CORS-checked, ETag).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..registry.registry import UnknownBot
from ..runtime.events import (
    HEARTBEAT,
    HEARTBEAT_TICK,
    format_sse,
    with_heartbeat,
)
from ..runtime.runner import TurnRequest, run_turn

router = APIRouter()


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


def _error_response(status: int, code: str, message: str, recoverable: bool = False) -> JSONResponse:
    # Pre-stream errors mirror the SSE error shape minus framing (docs/01 §Error codes).
    return JSONResponse(
        status_code=status,
        content={"type": "error", "code": code, "message": message, "recoverable": recoverable},
    )


@router.post("/api/v1/bots/{bot_id}/chat")
async def chat(bot_id: str, body: ChatBody, request: Request) -> Any:
    registry = request.app.state.registry
    sessions = request.app.state.sessions
    graphs = request.app.state.graphs
    heartbeat_s = request.app.state.registry.global_cfg.streaming.heartbeat_s

    # unknown bot → 404 (pre-stream)
    try:
        cfg = registry.get(bot_id)
    except UnknownBot:
        return _error_response(404, "unknown_bot", f"No bot with id '{bot_id}'.")

    # exactly one input field (message | choice | greeting:true) — docs/01 §Request
    inputs = sum(x is not None for x in (body.message, body.choice)) + (1 if body.greeting else 0)
    if inputs != 1:
        return _error_response(
            400, "invalid_request", "Provide exactly one of: message, choice, greeting."
        )

    # Enforce the per-bot limit on any free text the user can type — a plain message
    # OR a free-text reply to a quick-reply interrupt (choice.text).
    choice_text = body.choice.get("text") if body.choice else None
    longest = max(
        (len(t) for t in (body.message, choice_text) if isinstance(t, str)),
        default=0,
    )
    if longest > cfg.max_message_chars:
        return _error_response(
            400, "message_too_long",
            f"Message exceeds the {cfg.max_message_chars}-character limit.",
        )

    turn = TurnRequest(
        session_id=body.session_id,
        message=body.message,
        choice=body.choice,
        reply_to=body.reply_to,
        greeting=body.greeting,
        locale=(body.client.locale if body.client else None),
        auth_header=request.headers.get("authorization"),
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/bots/{bot_id}/config")
async def bootstrap(bot_id: str, request: Request, lang: str = "de") -> Any:
    registry = request.app.state.registry
    try:
        cfg = registry.get(bot_id)
    except UnknownBot:
        return _error_response(404, "unknown_bot", f"No bot with id '{bot_id}'.")

    origin = request.headers.get("origin")
    if origin is not None and origin not in cfg.embedding.allowed_origins:
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

    headers = {"ETag": etag, "Cache-Control": "public, max-age=300", "Vary": "Origin"}
    if origin is not None:
        headers["Access-Control-Allow-Origin"] = origin

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    return JSONResponse(content=payload, headers=headers)
