"""Batch 5a — shared graph helpers, esp. the source-URL scheme gate (#15). Tool
output is untrusted; a poisoned MCP result must not put a javascript:/data: URL on
the wire even if the widget also refuses it."""

from __future__ import annotations

from app.graphs._shared import coerce_results, host, safe_http_url, source_items


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


def test_source_items_drops_non_http_urls():
    rows = [
        {"title": "Legit", "url": "https://good.example/p"},
        {"title": "Evil", "url": "javascript:alert(document.cookie)"},
        {"title": "NoUrl"},  # no url → dropped
    ]
    items = source_items(rows)
    assert items == [{"title": "Legit", "source": "good.example", "url": "https://good.example/p"}]
