"""The only sanctioned event producers inside a graph fragment (docs/04 §3).

`text` is emitted implicitly by streaming a chat-model node (stream_mode="messages").
Everything else goes through these helpers so the gateway can translate a uniform
internal event stream to the wire protocol.
"""

from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer
from langgraph.types import interrupt


def emit_status(state: str, label: str, detail: str | None = None) -> None:
    get_stream_writer()({"type": "status", "state": state, "label": label, "detail": detail})


def emit_sources(message_id: str, sources: list[dict[str, Any]]) -> None:
    # sources: [{"title": str, "source": str, "url": str}], once per assistant message.
    get_stream_writer()({"type": "sources", "message_id": message_id, "sources": sources})


def ask_quick_replies(
    prompt: str, options: list[dict[str, Any]], allow_free_text: bool = True
) -> Any:
    """Interrupt awaiting a choice. The gateway assigns `reply_to` on translation and
    feeds the normalized reply back as this call's return value on resume."""
    return interrupt(
        {
            "interrupt_kind": "quick_replies",
            "prompt": prompt,
            "options": options,
            "allow_free_text": allow_free_text,
        }
    )


def resolve_choice(reply: Any, valid_ids: set[str]) -> str:
    """Normalize an interrupt reply to a route id. Handles a clicked choice (`id` set)
    and — when allow_free_text — a typed reply is left to the caller (raises here)."""
    if isinstance(reply, dict):
        rid = reply.get("id")
        if rid in valid_ids:
            return str(rid)
    raise ValueError(f"unresolved choice: {reply!r} (valid: {sorted(valid_ids)})")
