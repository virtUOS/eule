"""Shared fixtures. A `FakeClock` makes TTL behaviour deterministic (no sleeping)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from app.graphs.factory import GraphCache
from app.main import create_app
from app.registry.loader import load_and_validate
from app.registry.models import BotCfg, Defaults, GlobalCfg
from app.registry.registry import Registry
from app.runtime.sessions import Sessions

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

# Env with the referenced *_env secrets present, so check 3 passes for the real config.
VALID_ENV = {
    "VLLM_API_KEY": "test-key",
    "VLLM_SMALL_API_KEY": "test-key",
    "UOS_DOCS_MCP_TOKEN": "test-token",
}


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


def _make_registry() -> Registry:
    result = load_and_validate(CONFIG_DIR, env=VALID_ENV)
    assert result.ok, result.errors
    assert result.registry is not None
    return result.registry


@pytest.fixture
def registry() -> Registry:
    return _make_registry()


@pytest.fixture
def sessions(fake_clock: FakeClock) -> Sessions:
    counter = itertools.count(1)
    return Sessions(clock=fake_clock, id_factory=lambda: f"sess-{next(counter)}")


@pytest.fixture
def app(registry: Registry, sessions: Sessions):
    graphs = GraphCache(registry, sessions)
    return create_app(registry, sessions=sessions, graphs=graphs)


@pytest.fixture
async def client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- config-builder helpers for validation-check fixtures -------------------

MINIMAL_THEME = {
    "dark_mode": "auto",
    "light": {
        "--bg": "#ffffff",
        "--surface": "#f4f4f5",
        "--text": "#18181b",
        "--text-muted": "#6b6b70",
        "--primary": "#a6093d",
        "--accent": "#f2c879",
        "--on-primary": "#ffffff",
    },
    "dark": {
        "--bg": "#161618",
        "--surface": "#1e1e21",
        "--text": "#f4f4f5",
        "--text-muted": "#9a9aa1",
        "--primary": "#d95c7d",
        "--accent": "#f2c879",
        "--on-primary": "#ffffff",
    },
}


def make_global(**overrides) -> GlobalCfg:
    data = {
        "version": 1,
        "model_providers": {
            "default": {"base_url": "http://x/v1", "api_key_env": "VLLM_API_KEY"},
        },
        "mcp_servers": {},
        "defaults": Defaults().model_dump(),
        "theme": MINIMAL_THEME,
    }
    data.update(overrides)
    return GlobalCfg(**data)


def make_bot(**overrides) -> BotCfg:
    """Build a minimal valid BotCfg (overridable fields resolved from Defaults)."""
    d = Defaults()
    data = {
        "version": 1,
        "id": "sample",
        "name": "Sample",
        "model": {"provider": "default"},
        "session_ttl_s": d.session_ttl_s,
        "max_message_chars": d.max_message_chars,
        "history_max_turns": d.history_max_turns,
        "rate_limit": d.rate_limit.model_dump(),
        "guard": d.guard.model_dump(),
        "greeting": d.greeting.model_dump(),
    }
    data.update(overrides)
    return BotCfg(**data)
