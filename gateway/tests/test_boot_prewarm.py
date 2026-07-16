"""Boot-time graph prewarm (review batch 3, golden rule 4): fragment-level config
errors fail at create_app — i.e. at boot — not on the bot's first request."""

from __future__ import annotations

import pytest

from app.graphs.factory import GraphCache
from app.main import create_app
from app.registry.registry import Registry

from .conftest import make_bot, make_global


def test_bad_fragment_config_fails_at_boot(sessions):
    """A tool-agent bot whose effective allowlist is empty passes Registry
    construction (no validate-config here — simulating a drifted invariant) but must
    fail create_app, never 500 on the first user message."""
    bad = make_bot(
        id="broken", graph="tool-agent",
        tools={"mcp_servers": [], "allow": [], "deny": []},
    )
    registry = Registry(make_global(), {"broken": bad})
    with pytest.raises(ValueError, match="non-empty"):
        create_app(registry, sessions=sessions, graphs=GraphCache(registry, sessions))


def test_prewarm_builds_every_enabled_bot(registry, sessions):
    """After create_app, every enabled bot's compiled graph is cached — the real repo
    config (5 bots incl. router + subgraphs) builds fully offline."""
    graphs = GraphCache(registry, sessions)
    create_app(registry, sessions=sessions, graphs=graphs)
    enabled = {bot_id for bot_id in registry.ids() if registry.get(bot_id).enabled}
    assert set(graphs._cache) == enabled


def test_disabled_bots_are_not_prewarmed(sessions):
    built: list[str] = []

    class _SpyGraphs:
        def get(self, bot_id: str) -> object:
            built.append(bot_id)
            return object()

    on = make_bot(id="on")
    off = make_bot(id="off", enabled=False)
    registry = Registry(make_global(), {"on": on, "off": off})
    create_app(registry, sessions=sessions, graphs=_SpyGraphs())
    assert built == ["on"]
