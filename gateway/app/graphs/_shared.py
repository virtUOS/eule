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


# Keys a server might wrap its result list under. `result` (singular) matters most:
# FastMCP wraps a tool that returns a bare `list` as structuredContent={"result": [...]}.
_LIST_KEYS = ("results", "result", "items", "data", "hits", "documents", "matches")


def coerce_results(structured: Any, text: str | None) -> list[dict[str, Any]]:
    """Normalize a tool result into a list of dict rows. Tolerant of how MCP servers
    shape search output: a bare list, or a dict wrapping the list under a common key
    (`results`/`result`/`items`/…), or a single list-valued key, or a JSON text body
    when there's no structured content. Returns [] only when nothing list-like is found."""
    payload: Any = structured
    if payload is None and text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        payload = _unwrap_list(payload)
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _unwrap_list(payload: dict[str, Any]) -> Any:
    """Pull the result list out of a dict envelope: a known key first, else the sole
    list-valued key. Falls back to the dict itself (treated as a single row)."""
    for key in _LIST_KEYS:
        if isinstance(payload.get(key), list):
            return payload[key]
    list_values = [v for v in payload.values() if isinstance(v, list)]
    if len(list_values) == 1:
        return list_values[0]
    return [payload]  # a lone result object → one row


def describe_result(structured: Any, text: str | None) -> str:
    """Compact, log-safe summary of a raw tool result — the top-level shape and keys,
    plus a short text prefix — so a parse-miss can be diagnosed without dumping payloads."""
    if isinstance(structured, dict):
        shape = f"dict keys={sorted(structured)[:12]}"
    elif isinstance(structured, list):
        shape = f"list len={len(structured)}"
    elif structured is not None:
        shape = f"{type(structured).__name__}"
    else:
        shape = "none"
    return f"structured={shape} text[:200]={(text or '')[:200]!r}"


def build_tool_args(input_schema: dict[str, Any] | None, value: Any, *, fallback: str) -> dict[str, Any]:
    """Map a single-value tool call to the parameter name the server actually declares,
    read from the tool's JSON input schema. Servers name these differently (Osnabrück's
    `uos_search` wants `search_term`, not `query`), so hardcoding the key makes every
    call fail with a missing-argument error. Picks the sole required property, else the
    sole property, else `fallback`."""
    schema = input_schema or {}
    props = schema.get("properties") or {}
    required = [name for name in (schema.get("required") or []) if name in props]
    if len(required) == 1:
        key = required[0]
    elif len(props) == 1:
        key = next(iter(props))
    else:
        key = fallback
    return {key: value}


def page_text(structured: Any, text: str | None) -> str:
    """A fetch result → its page body (markdown). Tolerates a structured dict (common
    keys `markdown`/`content`/`text`), a bare structured string, or a plain text body."""
    if isinstance(structured, dict):
        for key in ("markdown", "content", "text"):
            value = structured.get(key)
            if isinstance(value, str):
                return value
    if isinstance(structured, str):
        return structured
    return text or ""


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
