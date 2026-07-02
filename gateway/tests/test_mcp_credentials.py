"""Prereq A — MCP server credential field (bearer_token_env)."""

from __future__ import annotations

from app.registry.models import McpServer
from app.registry.registry import Registry
from app.registry.validation import check_all

from .conftest import make_global


def test_mcp_server_without_credential_is_fine():
    g = make_global(mcp_servers={"docs": {"transport": "streamable-http", "url": "https://x"}})
    errors, _ = check_all(g, {}, {})
    assert not [e for e in errors if "check 3" in e and "mcp_servers" in e]


def test_mcp_server_missing_bearer_env_fails_check3():
    g = make_global(
        mcp_servers={
            "docs": {"transport": "streamable-http", "url": "https://x", "bearer_token_env": "DOCS_TOKEN"}
        }
    )
    errors, _ = check_all(g, {}, {})
    assert any("check 3" in e and "DOCS_TOKEN" in e for e in errors)


def test_mcp_server_bearer_env_resolves_when_set():
    g = make_global(
        mcp_servers={
            "docs": {"transport": "streamable-http", "url": "https://x", "bearer_token_env": "DOCS_TOKEN"}
        }
    )
    errors, _ = check_all(g, {}, {"DOCS_TOKEN": "secret-value"})
    assert not [e for e in errors if "DOCS_TOKEN" in e]


def test_registry_resolve_mcp_bearer():
    g = make_global()
    registry = Registry(g, {})
    with_token = McpServer(transport="streamable-http", url="https://x", bearer_token_env="DOCS_TOKEN")
    without_token = McpServer(transport="streamable-http", url="https://y")

    assert registry.resolve_mcp_bearer(with_token, env={"DOCS_TOKEN": "abc"}) == "abc"
    assert registry.resolve_mcp_bearer(with_token, env={}) is None
    assert registry.resolve_mcp_bearer(without_token, env={"DOCS_TOKEN": "abc"}) is None


def test_registry_provider_resolves_any_named_provider():
    g = make_global(
        model_providers={
            "default": {"base_url": "https://a", "api_key_env": "A_KEY"},
            "fast-small": {"base_url": "https://b", "api_key_env": "B_KEY"},
        }
    )
    registry = Registry(g, {})
    p = registry.provider("fast-small", env={"B_KEY": "b-secret"})
    assert p.name == "fast-small"
    assert p.base_url == "https://b"
    assert p.api_key == "b-secret"
