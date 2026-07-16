"""Shared fragment helpers — message extraction and tolerant tool-result parsing.

Tool output is UNTRUSTED (docs/04 §7). `safe_http_url` is the gateway-side scheme
gate for source URLs: even though the widget also refuses non-http(s) links, the
graph is the natural defense-in-depth choke point — a poisoned MCP result must not be
able to emit a `javascript:`/`data:` URL onto the wire in the first place.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage

from .skeleton import BotState


def last_user_text(state: BotState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


def host(url: str) -> str:
    net = urlparse(url).netloc
    return net[4:] if net.startswith("www.") else net


def safe_http_url(raw: str) -> str | None:
    """Return the URL only if it is http(s); otherwise None (drop it)."""
    try:
        scheme = urlparse(raw).scheme.lower()
    except ValueError:
        return None
    return raw if scheme in ("http", "https") else None


def coerce_results(structured: Any, text: str | None) -> list[dict[str, Any]]:
    """Normalize a tool result into a list of dict rows. Tolerates structured output
    or a JSON text body; a dict payload is unwrapped from its `results` key."""
    payload: Any = structured
    if payload is None and text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def source_items(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Rows → citation items [{title, source, url}], keeping only http(s) URLs."""
    out: list[dict[str, str]] = []
    for row in rows:
        raw = row.get("url")
        url = safe_http_url(str(raw)) if raw else None
        if url is None:
            continue
        out.append({"title": str(row.get("title") or url), "source": host(url), "url": url})
    return out
