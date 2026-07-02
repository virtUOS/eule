"""Typed runtime access to config. Nothing downstream reads YAML — only these objects
(docs/03 §Runtime access)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .models import BotCfg, GlobalCfg, McpServer, ModelProvider
from .theme import ResolvedTheme, resolve_theme


class UnknownBot(KeyError):
    """Raised by Registry.get for an id not in the registry (→ protocol unknown_bot)."""


@dataclass(frozen=True)
class ResolvedProvider:
    name: str
    base_url: str
    api_key: str
    default_model: str | None
    timeout_s: int
    max_retries: int


class Registry:
    def __init__(self, gcfg: GlobalCfg, bots: Mapping[str, BotCfg]) -> None:
        self._gcfg = gcfg
        self._bots = dict(bots)

    @property
    def global_cfg(self) -> GlobalCfg:
        return self._gcfg

    def ids(self) -> list[str]:
        return list(self._bots)

    def get(self, bot_id: str) -> BotCfg:
        try:
            return self._bots[bot_id]
        except KeyError as e:
            raise UnknownBot(bot_id) from e

    def resolve_provider(
        self, cfg: BotCfg, env: Mapping[str, str] | None = None
    ) -> ResolvedProvider:
        env = os.environ if env is None else env
        prov: ModelProvider = self._gcfg.model_providers[cfg.model.provider]
        return ResolvedProvider(
            name=cfg.model.provider,
            base_url=prov.base_url,
            api_key=env.get(prov.api_key_env, ""),
            default_model=prov.default_model,
            timeout_s=prov.timeout_s,
            max_retries=prov.max_retries,
        )

    def mcp_for(self, cfg: BotCfg) -> list[McpServer]:
        return [self._gcfg.mcp_servers[name] for name in cfg.tools.mcp_servers]

    def resolve_theme(self, cfg: BotCfg) -> ResolvedTheme:
        return resolve_theme(self._gcfg.theme, cfg.theme)
