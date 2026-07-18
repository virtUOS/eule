"""Batch 5a — shared graph helpers, esp. the source-URL scheme gate (#15). Tool
output is untrusted; a poisoned MCP result must not put a javascript:/data: URL on
the wire even if the widget also refuses it."""

from __future__ import annotations

from app.graphs._shared import (
    build_tool_args,
    coerce_results,
    host,
    page_text,
    safe_http_url,
    source_items,
)


def test_build_tool_args_uses_declared_param_name():
    # the real uos_search shape: one required param named search_term
    schema = {"type": "object", "properties": {"search_term": {"type": "string"}}, "required": ["search_term"]}
    assert build_tool_args(schema, "vpn", fallback="query") == {"search_term": "vpn"}
    # sole required arg picked even when optional params exist
    schema2 = {
        "properties": {"search_term": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["search_term"],
    }
    assert build_tool_args(schema2, "vpn", fallback="query") == {"search_term": "vpn"}
    # sole property, none marked required → use it
    assert build_tool_args({"properties": {"url": {"type": "string"}}}, "u", fallback="x") == {"url": "u"}
    # ambiguous (no/2+ required, 2+ props) or missing schema → fallback
    assert build_tool_args({"properties": {"a": {}, "b": {}}}, "v", fallback="query") == {"query": "v"}
    assert build_tool_args(None, "v", fallback="query") == {"query": "v"}


def test_safe_http_url_allows_only_http_s():
    assert safe_http_url("https://a.example/x") == "https://a.example/x"
    assert safe_http_url("http://a.example") == "http://a.example"
    assert safe_http_url("javascript:alert(1)") is None
    assert safe_http_url("data:text/html,<script>") is None
    assert safe_http_url("ftp://a.example") is None
    assert safe_http_url("not a url") is None


def test_host_strips_www():
    assert host("https://www.uni.example/x") == "uni.example"
    assert host("https://rz.uni.example/vpn") == "rz.uni.example"


def test_coerce_results_tolerates_shapes():
    assert coerce_results({"results": [{"url": "x"}]}, None) == [{"url": "x"}]
    assert coerce_results(None, '{"results": [{"url": "y"}]}') == [{"url": "y"}]
    assert coerce_results(None, "[{\"url\": \"z\"}]") == [{"url": "z"}]
    assert coerce_results(None, "not json") == []
    assert coerce_results(None, None) == []


def test_coerce_results_unwraps_server_envelopes():
    # FastMCP wraps a bare-list return under singular `result` — the shape that made
    # uos_search look empty.
    assert coerce_results({"result": [{"url": "a"}]}, None) == [{"url": "a"}]
    # other common list keys
    assert coerce_results({"items": [{"url": "b"}]}, None) == [{"url": "b"}]
    assert coerce_results({"hits": [{"url": "c"}]}, None) == [{"url": "c"}]
    # a bare top-level list of rows
    assert coerce_results([{"url": "d"}], None) == [{"url": "d"}]
    # sole list-valued key under an unknown name → unwrap it
    assert coerce_results({"documentsList": [{"url": "e"}]}, None) == [{"url": "e"}]
    # a lone result object (no list anywhere) → treated as one row
    assert coerce_results({"url": "f", "title": "F"}, None) == [{"url": "f", "title": "F"}]


def test_page_text_extracts_common_fields():
    assert page_text({"markdown": "# Hi"}, None) == "# Hi"
    assert page_text({"content": "body"}, None) == "body"
    assert page_text({"text": "plain"}, None) == "plain"
    assert page_text("just a string", None) == "just a string"
    assert page_text(None, "fallback text") == "fallback text"
    assert page_text({"unrelated": 1}, "fallback") == "fallback"


def test_source_items_drops_non_http_urls():
    rows = [
        {"title": "Legit", "url": "https://good.example/p"},
        {"title": "Evil", "url": "javascript:alert(document.cookie)"},
        {"title": "NoUrl"},  # no url → dropped
    ]
    items = source_items(rows)
    assert items == [{"title": "Legit", "source": "good.example", "url": "https://good.example/p"}]
