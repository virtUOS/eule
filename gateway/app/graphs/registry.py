"""Fragment dispatch (docs/03: "config only references which graph a bot uses").

Graphs live in code, never as config data — this module is the one place a bot's
`graph` name is resolved to the code that builds its fragment. Adding a new bot's
graph means adding one entry here (plus the fragment module itself); no other file
needs to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..registry.models import BotCfg
from .echo import build_echo_fragment
from .it_helpdesk import build_it_helpdesk_fragment
from .skeleton import GraphFragment

if TYPE_CHECKING:
    from ..registry.registry import Registry


class UnknownGraph(KeyError):
    """Raised when a bot's `graph` name has no registered fragment builder
    (→ validate-config check 13; fails boot, per golden rule 4)."""


# A fragment builder gets the bot's config and the registry (to resolve its model
# provider and MCP servers from config). Simple fragments ignore the registry.
FragmentBuilder = Callable[[BotCfg, "Registry"], GraphFragment]

FRAGMENT_BUILDERS: dict[str, FragmentBuilder] = {
    "echo": lambda cfg, registry: build_echo_fragment(),
    "it-helpdesk": lambda cfg, registry: build_it_helpdesk_fragment(cfg, registry),
}


def known_graphs() -> list[str]:
    return list(FRAGMENT_BUILDERS)


def build_fragment(cfg: BotCfg, registry: "Registry") -> GraphFragment:
    try:
        builder = FRAGMENT_BUILDERS[cfg.graph]
    except KeyError:
        raise UnknownGraph(cfg.graph) from None
    return builder(cfg, registry)
