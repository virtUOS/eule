"""Fragment dispatch (docs/03: "config only references which graph a bot uses").

Graphs live in code, never as config data — this module is the one place a bot's
`graph` name is resolved to the code that builds its fragment. Adding a new bot's
graph means adding one entry here (plus the fragment module itself); no other file
needs to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, ConfigDict

from ..registry.models import BotCfg
from .echo import build_echo_fragment
from .it_helpdesk import build_it_helpdesk_fragment
from .passthrough import PassthroughParams, build_passthrough_fragment
from .router import RouterParams, build_router_fragment
from .skeleton import GraphFragment
from .tool_agent import ToolAgentParams, build_tool_agent_fragment

if TYPE_CHECKING:
    from ..registry.registry import Registry


class UnknownGraph(KeyError):
    """Raised when a bot's `graph` name has no registered fragment builder
    (→ validate-config check 13; fails boot, per golden rule 4)."""


class NoParams(BaseModel):
    """Fragments that take no `graph_params`. extra="forbid" → any key is a boot error."""

    model_config = ConfigDict(extra="forbid")


# A fragment builder gets the bot's config and the registry (to resolve its model
# provider and MCP servers from config). Simple fragments ignore the registry.
FragmentBuilder = Callable[[BotCfg, "Registry"], GraphFragment]

FRAGMENT_BUILDERS: dict[str, FragmentBuilder] = {
    # bespoke fragments (in-tree gateway code)
    "echo": lambda cfg, registry: build_echo_fragment(),
    "it-helpdesk": lambda cfg, registry: build_it_helpdesk_fragment(cfg, registry),
    # stock fragments (config-only bots — BUILD_PLAN steps 9 + 9c)
    "passthrough": lambda cfg, registry: build_passthrough_fragment(cfg, registry),
    "tool-agent": lambda cfg, registry: build_tool_agent_fragment(cfg, registry),
    "router": lambda cfg, registry: build_router_fragment(cfg, registry),
}

# Every graph declares its `graph_params` model (check 14). Bespoke fragments take
# none — a stray graph_params block on them fails boot instead of being ignored.
FRAGMENT_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "echo": NoParams,
    "it-helpdesk": NoParams,
    "passthrough": PassthroughParams,
    "tool-agent": ToolAgentParams,
    "router": RouterParams,
}

# The two registries MUST cover the same graphs: a fragment registered without a
# params model would make check 14 silently skip it — graph_params on that bot would
# be ignored, which is exactly the failure mode check 14 exists to prevent. Fail at
# import (= at boot), per golden rule 4.
if FRAGMENT_BUILDERS.keys() != FRAGMENT_PARAM_MODELS.keys():
    raise RuntimeError(
        "FRAGMENT_BUILDERS and FRAGMENT_PARAM_MODELS must register the same graphs; "
        f"mismatch: {sorted(FRAGMENT_BUILDERS.keys() ^ FRAGMENT_PARAM_MODELS.keys())}"
    )


def known_graphs() -> list[str]:
    return list(FRAGMENT_BUILDERS)


def build_fragment(cfg: BotCfg, registry: "Registry") -> GraphFragment:
    try:
        builder = FRAGMENT_BUILDERS[cfg.graph]
    except KeyError:
        raise UnknownGraph(cfg.graph) from None
    return builder(cfg, registry)
