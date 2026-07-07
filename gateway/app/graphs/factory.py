"""Compiled-graph cache (docs/03 §Runtime access: registry.graph_for).

One compiled graph per bot, cached. Routers (subgraph composition) land in Step 5b;
every other bot's fragment is resolved by `cfg.graph` via the fragment registry.
"""

from __future__ import annotations

from typing import Any

from ..registry.models import BotCfg
from ..registry.registry import Registry
from ..runtime.sessions import Sessions
from .model import build_chat_model
from .registry import build_fragment
from .skeleton import build_bot_graph


def build_compiled_graph(cfg: BotCfg, checkpointer: Any, registry: Registry) -> Any:
    if cfg.routes is not None:
        raise NotImplementedError("router (subgraph composition) arrives in Step 5b")
    guard_model = None
    if cfg.guard.enabled:
        assert cfg.guard.provider is not None  # guaranteed by validation check 6
        guard_model = build_chat_model(registry.provider(cfg.guard.provider))
    return build_bot_graph(
        cfg, tools=[], fragment=build_fragment(cfg, registry), checkpointer=checkpointer,
        guard_model=guard_model,
    )


class GraphCache:
    def __init__(self, registry: Registry, sessions: Sessions) -> None:
        self._registry = registry
        self._sessions = sessions
        self._cache: dict[str, Any] = {}

    def get(self, bot_id: str) -> Any:
        if bot_id not in self._cache:
            cfg = self._registry.get(bot_id)
            self._cache[bot_id] = build_compiled_graph(cfg, self._sessions.checkpointer, self._registry)
        return self._cache[bot_id]
