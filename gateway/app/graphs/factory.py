"""Compiled-graph cache (docs/03 §Runtime access: registry.graph_for).

One compiled graph per bot, cached. Routers (subgraph composition) land in Step 5b;
until then every bot uses the echo stub fragment.
"""

from __future__ import annotations

from typing import Any

from ..registry.models import BotCfg
from ..registry.registry import Registry
from ..runtime.sessions import Sessions
from .echo import build_echo_fragment
from .skeleton import build_bot_graph


def build_compiled_graph(cfg: BotCfg, checkpointer: Any) -> Any:
    if cfg.routes is not None:
        raise NotImplementedError("router (subgraph composition) arrives in Step 5b")
    return build_bot_graph(cfg, tools=[], fragment=build_echo_fragment(), checkpointer=checkpointer)


class GraphCache:
    def __init__(self, registry: Registry, sessions: Sessions) -> None:
        self._registry = registry
        self._sessions = sessions
        self._cache: dict[str, Any] = {}

    def get(self, bot_id: str) -> Any:
        if bot_id not in self._cache:
            cfg = self._registry.get(bot_id)
            self._cache[bot_id] = build_compiled_graph(cfg, self._sessions.checkpointer)
        return self._cache[bot_id]
