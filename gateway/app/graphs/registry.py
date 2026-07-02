"""Fragment dispatch (docs/03: "config only references which graph a bot uses").

Graphs live in code, never as config data — this module is the one place a bot's
`graph` name is resolved to the code that builds its fragment. Adding a new bot's
graph means adding one entry here (plus the fragment module itself); no other file
needs to change.
"""

from __future__ import annotations

from typing import Callable

from ..registry.models import BotCfg
from .echo import build_echo_fragment
from .skeleton import GraphFragment


class UnknownGraph(KeyError):
    """Raised when a bot's `graph` name has no registered fragment builder
    (→ validate-config check 13; fails boot, per golden rule 4)."""


FragmentBuilder = Callable[[BotCfg], GraphFragment]

# bot_id-agnostic: a fragment builder only needs the bot's own config (tools, prompt).
FRAGMENT_BUILDERS: dict[str, FragmentBuilder] = {
    "echo": lambda cfg: build_echo_fragment(),
}


def known_graphs() -> list[str]:
    return list(FRAGMENT_BUILDERS)


def build_fragment(cfg: BotCfg) -> GraphFragment:
    try:
        builder = FRAGMENT_BUILDERS[cfg.graph]
    except KeyError:
        raise UnknownGraph(cfg.graph) from None
    return builder(cfg)
