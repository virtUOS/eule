"""Stock `router` fragment — the orchestrator / front door (docs/04 §6b;
BUILD_PLAN step 9c). Golden rule 8: routing is bot logic, never gateway logic —
this is just a fragment; the gateway drives it like any other bot.

Composes the routed bots' fragments **as subgraphs** — it does NOT merge their
tools, so each sub-bot keeps its own structural scoping (T11.6: a sub-bot reached
via the router has exactly the tool surface its own config allows).

Menu-first (v1): the entry interrupts with one `quick_replies` option per
`routes.targets[]` (no free text; classifier routing is v2). After a choice, a
`handoff` interrupt asks for the question (free text allowed) and carries the
"ask about something else" escape back to the menu. Each routed answer returns to
`handoff`, so the escape stays one tap away — the front-door bot therefore ends
every turn `awaiting_input`, never `complete`.

Sticky routing lives in `scratch["route"]`, persisted across interrupt-resume
turns by the composite checkpoint (docs/04 §6b: "interrupts across routing just
work"). A FRESH `message` turn resets `scratch` (docs/04 §8 input semantics), so a
client that lost its pending interrupt falls back to the menu — honest recovery,
not a bug.

Sub-bot interrupts pause inside the routed subgraph and resume through the same
composite checkpoint with no routing logic on resume (T5.5).

Selected via `graph: "router"`; requires a `routes` block (check 14); nested
routers are rejected (check 10). Prompts are localized via `graph_params`
(`ctx.locale` picks the language; defaults below).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import START
from pydantic import BaseModel, ConfigDict, Field

from .emit import ask_quick_replies, resolve_choice
from .skeleton import BotGraphBuilder, BotState, GraphFragment

if TYPE_CHECKING:
    from ..registry.models import BotCfg
    from ..registry.registry import Registry

MENU_CHOICE = "__menu__"  # reserved handoff option id: back to the menu

_DEFAULT_MENU_PROMPT = {"de": "Womit kann ich helfen?", "en": "What can I help with?"}
_DEFAULT_ASK_PROMPT = {"de": "Was möchtest du wissen?", "en": "What would you like to know?"}
_DEFAULT_ESCAPE_LABEL = {"de": "Anderes Thema wählen", "en": "Ask about something else"}


class RouterParams(BaseModel):
    """Per-bot `graph_params` for `graph: "router"` (validated at boot, check 14).
    Each is a base-language → text map merged over the built-in de/en defaults."""

    model_config = ConfigDict(extra="forbid")
    menu_prompt: dict[str, str] = Field(default_factory=dict)
    ask_prompt: dict[str, str] = Field(default_factory=dict)
    escape_label: dict[str, str] = Field(default_factory=dict)


def _pick(overrides: dict[str, str], defaults: dict[str, str], locale: str | None) -> str:
    table = {**defaults, **overrides}
    base = (locale or "").split("-")[0].lower()
    return table.get(base) or table.get("de") or next(iter(table.values()))


def _compile_subgraph(fragment: GraphFragment) -> Any:
    """A sub-bot's fragment as a standalone graph, compiled WITHOUT a checkpointer —
    nested in the router it persists through the parent's checkpoint (one composite
    checkpoint per session)."""
    b = BotGraphBuilder()
    fragment.flow(b)
    b.g.add_edge(START, b.entry)
    return b.g.compile()


def build_router_fragment(
    cfg: "BotCfg",
    registry: "Registry",
    *,
    subgraph_fragments: dict[str, GraphFragment] | None = None,
) -> GraphFragment:
    """`subgraph_fragments` is a test seam (inject fake sub-bots keyed by target bot
    id); production builds each target's fragment from ITS OWN config — that is what
    preserves per-sub-bot structural scoping."""
    params = RouterParams(**cfg.graph_params)  # boot-validated (check 14); re-assert
    routes = cfg.routes
    if routes is None or not routes.targets:
        # check 14 guarantees this at boot; guard the direct-construction path too.
        raise ValueError(f"bot '{cfg.id}' (router) requires a routes block with targets")
    targets = routes.targets

    if subgraph_fragments is None:
        # Late import: graphs.registry imports this module (fragment dispatch).
        from .registry import build_fragment

        subgraph_fragments = {t.bot: build_fragment(registry.get(t.bot), registry) for t in targets}

    valid = {t.bot for t in targets}
    # ":" is reserved in LangGraph node names (namespace separator); the prefix keeps
    # target nodes distinct from the router's own ("menu"/"handoff") for any bot id.
    node_name = {t.bot: f"bot_{t.bot}" for t in targets}

    def flow(b: BotGraphBuilder) -> None:
        async def menu(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            ctx = config["configurable"]["ctx"]
            reply = ask_quick_replies(
                _pick(params.menu_prompt, _DEFAULT_MENU_PROMPT, ctx.locale),
                [{"id": t.bot, "label": t.label} for t in targets],
                allow_free_text=False,  # v1: menu only; classifier routing is v2
            )
            route = resolve_choice(reply, valid_ids=valid)
            return {"scratch": {**state.get("scratch", {}), "route": route}}

        async def handoff(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            ctx = config["configurable"]["ctx"]
            reply = ask_quick_replies(
                _pick(params.ask_prompt, _DEFAULT_ASK_PROMPT, ctx.locale),
                [{"id": MENU_CHOICE, "label": _pick(params.escape_label, _DEFAULT_ESCAPE_LABEL, ctx.locale)}],
                allow_free_text=True,
            )
            scratch = dict(state.get("scratch", {}))
            choice_id = reply.get("id") if isinstance(reply, dict) else None
            text = reply.get("text") if isinstance(reply, dict) else None
            if choice_id == MENU_CHOICE or not text:
                # escape (or malformed reply): drop stickiness, fall back to the menu
                scratch.pop("route", None)
                return {"scratch": scratch}
            # free-text question: a resume carries no HumanMessage (docs/04 §5) —
            # append it here so the routed sub-bot sees what was asked.
            return {"messages": [HumanMessage(content=str(text))], "scratch": scratch}

        def after_handoff(state: BotState) -> str:
            route = state.get("scratch", {}).get("route")
            messages = state.get("messages", [])
            if route in valid and messages and isinstance(messages[-1], HumanMessage):
                return node_name[route]
            return "menu"

        b.add_node("menu", menu)
        b.add_node("handoff", handoff)
        b.set_entry_after_guard("menu")
        b.add_edge("menu", "handoff")  # after a choice, ask for the question

        for target_bot, fragment in subgraph_fragments.items():
            b.add_node(node_name[target_bot], _compile_subgraph(fragment))
            # after a routed answer, back to handoff: next question or the escape
            b.add_edge(node_name[target_bot], "handoff")

        b.add_conditional_edges(
            "handoff",
            after_handoff,
            {"menu": "menu", **{n: n for n in node_name.values()}},
        )

    return GraphFragment(flow)
