"""Stock `router` fragment — the orchestrator / front door (docs/04 §6b;
BUILD_PLAN steps 9c + 12). Golden rule 8: routing is bot logic, never gateway
logic — this is just a fragment; the gateway drives it like any other bot.

Composes the routed bots' fragments **as subgraphs** — it does NOT merge their
tools, so each sub-bot keeps its own structural scoping (T11.6: a sub-bot reached
via the router has exactly the tool surface its own config allows).

Two modes (`routes.mode`):
- **menu** (default): the entry interrupts with one `quick_replies` option per
  `routes.targets[]`, no free text. A click selects the lane.
- **classifier** (step 12): the menu stays but free text is allowed. A CLICK routes
  exactly as in menu mode; a TYPED message is classified onto a target by the
  router's own cheap model, with the menu as the universal fallback. The decision
  ladder for an unrouted typed message: (1) `context.topic` exactly matching a
  target id → deterministic, zero model calls; (2) one classifier call — exact-token
  reply from {target ids…, none}, TAG_NOSTREAM, latest message only (guard-grade
  hardening); (3) anything else → menu, with the typed question KEPT in history so
  a subsequent click needs no retyping. Misrouting is not a scope breach (each
  sub-bot keeps its own allowlist) and injection is self-inflicted (check 11
  guarantees every target is auth-compatible with the router).

After a route is chosen, a `handoff` interrupt asks for the question (free text)
and carries the "ask about something else" escape back to the menu. Each routed
answer returns to `handoff` — the front-door bot ends every turn `awaiting_input`.

Sticky routing lives in `scratch["route"]`, persisted across interrupt-resume
turns by the composite checkpoint. A FRESH `message` turn resets `scratch`
(docs/04 §8 input semantics) — in classifier mode that fresh message is simply
classified again; in menu mode it falls back to the menu.

Sub-bot interrupts pause inside the routed subgraph and resume through the same
composite checkpoint with no routing logic on resume (T5.5).

Selected via `graph: "router"`; requires a `routes` block (check 14); nested
routers are rejected (check 10). Prompts are localized via `graph_params`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Hashable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import START
from pydantic import BaseModel, ConfigDict, Field

from ..runtime import metrics
from ._shared import last_user_text
from .emit import ask_quick_replies, emit_status
from .model import build_chat_model
from .skeleton import BotGraphBuilder, BotState, GraphFragment

if TYPE_CHECKING:
    from ..registry.models import BotCfg
    from ..registry.registry import Registry

MENU_CHOICE = "__menu__"  # reserved handoff option id: back to the menu

_DEFAULT_MENU_PROMPT = {"de": "Womit kann ich helfen?", "en": "What can I help with?"}
_DEFAULT_ASK_PROMPT = {"de": "Was möchtest du wissen?", "en": "What would you like to know?"}
_DEFAULT_ESCAPE_LABEL = {"de": "Anderes Thema wählen", "en": "Ask about something else"}
_DEFAULT_CLASSIFY_STATUS = {
    "de": "Finde den passenden Assistenten…",
    "en": "Finding the right assistant…",
}


class RouterParams(BaseModel):
    """Per-bot `graph_params` for `graph: "router"` (validated at boot, check 14).
    Each is a base-language → text map merged over the built-in de/en defaults."""

    model_config = ConfigDict(extra="forbid")
    menu_prompt: dict[str, str] = Field(default_factory=dict)
    ask_prompt: dict[str, str] = Field(default_factory=dict)
    escape_label: dict[str, str] = Field(default_factory=dict)
    classify_status: dict[str, str] = Field(default_factory=dict)


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
    classifier_model: BaseChatModel | None = None,
) -> GraphFragment:
    """`subgraph_fragments`/`classifier_model` are test seams. Production builds each
    target's fragment from ITS OWN config — that is what preserves per-sub-bot
    structural scoping — and, in classifier mode, resolves the classifier from the
    router's `model.provider`."""
    params = RouterParams(**cfg.graph_params)  # boot-validated (check 14); re-assert
    routes = cfg.routes
    if routes is None or not routes.targets:
        # check 14 guarantees this at boot; guard the direct-construction path too.
        raise ValueError(f"bot '{cfg.id}' (router) requires a routes block with targets")
    targets = routes.targets
    classifier_mode = routes.mode == "classifier"

    if subgraph_fragments is None:
        # Late import: graphs.registry imports this module (fragment dispatch).
        from .registry import build_fragment

        subgraph_fragments = {t.bot: build_fragment(registry.get(t.bot), registry) for t in targets}

    if classifier_mode and classifier_model is None:
        classifier_model = build_chat_model(registry.resolve_provider(cfg))

    valid = {t.bot for t in targets}
    labels = {t.bot: t.label for t in targets}
    # ":" is reserved in LangGraph node names (namespace separator); the prefix keeps
    # target nodes distinct from the router's own nodes for any bot id.
    node_name = {t.bot: f"bot_{t.bot}" for t in targets}

    def _hint(t: Any) -> str:
        """Classifier routing description: route_hint → target bot's description →
        the menu label. (Injected test fragments may not exist in the registry.)"""
        if t.route_hint:
            return str(t.route_hint)
        try:
            desc = registry.get(t.bot).description
        except Exception:
            desc = None
        return str(desc or t.label)

    hints = {t.bot: _hint(t) for t in targets}
    classify_system = SystemMessage(
        "You are a strict router for a university assistant. Given the user's message, "
        "reply with EXACTLY one word: the id of the best-matching assistant below, or "
        "'none' if none clearly fits. No punctuation, no explanation.\n\nAssistants:\n"
        + "\n".join(f"- {bot_id}: {hints[bot_id]}" for bot_id in hints)
    )

    async def _classify(text: str, locale: str | None) -> str | None:
        """One cheap-model call → a target id or None (menu fallback). Guard-grade:
        latest message only, NOSTREAM, exact leading-token match on a closed set."""
        assert classifier_model is not None  # classifier_mode ⇒ resolved above
        emit_status("thinking", _pick(params.classify_status, _DEFAULT_CLASSIFY_STATUS, locale))
        try:
            result = await classifier_model.ainvoke(
                [classify_system, HumanMessage(content=text)], config={"tags": [TAG_NOSTREAM]}
            )
        except Exception:
            metrics.ROUTER_CLASSIFIER.labels(cfg.id, "error").inc()
            return None  # fail-safe = the menu
        leading = re.split(r"[^a-z0-9_-]+", str(result.content).strip().lower(), maxsplit=1)[0]
        if leading in valid:
            metrics.ROUTER_CLASSIFIER.labels(cfg.id, "routed").inc()
            return leading
        outcome = "none" if leading == "none" else "unparseable"
        metrics.ROUTER_CLASSIFIER.labels(cfg.id, outcome).inc()
        return None

    def _routed_status(route: str) -> None:
        # Transparency: show which lane was chosen before the answer streams.
        emit_status("thinking", f"→ {labels[route]}")

    def flow(b: BotGraphBuilder) -> None:
        async def dispatch(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            """Classifier-mode entry (fresh turns only — resumes re-enter their
            interrupt node directly). Decision ladder: context.topic → classify →
            menu. Menu mode never uses this node."""
            ctx = config["configurable"]["ctx"]
            scratch = dict(state.get("scratch", {}))
            turn = state.get("turn_input", {})
            kind = turn.get("kind")
            topic = (turn.get("context") or {}).get("topic")

            if topic in valid:  # 1) deterministic shortcut, zero model calls
                scratch["route"] = topic
                metrics.ROUTER_CHOICES.labels(cfg.id, str(topic), "context").inc()
                _routed_status(str(topic))
                scratch["go"] = "sub" if kind == "text" else "handoff"
                return {"scratch": scratch}

            if kind == "text":  # 2) classify the (already-in-state) typed message
                target = await _classify(last_user_text(state), ctx.locale)
                if target is not None:
                    scratch["route"] = target
                    metrics.ROUTER_CHOICES.labels(cfg.id, target, "classifier").inc()
                    _routed_status(target)
                    scratch["go"] = "sub"
                    return {"scratch": scratch}

            scratch["go"] = "menu"  # 3) greeting, or no confident classification
            return {"scratch": scratch}

        async def menu(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            ctx = config["configurable"]["ctx"]
            reply = ask_quick_replies(
                _pick(params.menu_prompt, _DEFAULT_MENU_PROMPT, ctx.locale),
                [{"id": t.bot, "label": t.label} for t in targets],
                allow_free_text=classifier_mode,  # step 12: typing classifies; menu mode: click only
            )
            scratch = dict(state.get("scratch", {}))
            choice_id = reply.get("id") if isinstance(reply, dict) else None
            text = ((reply.get("text") if isinstance(reply, dict) else None) or "").strip()

            if choice_id in valid:  # a click routes exactly as in menu mode
                scratch["route"] = choice_id
                metrics.ROUTER_CHOICES.labels(cfg.id, str(choice_id), "menu").inc()
                # a question typed earlier (kept in history) is consumed now: no retyping
                scratch["go"] = "sub" if scratch.pop("pending_question", False) else "handoff"
                return {"scratch": scratch}

            if classifier_mode and text:
                target = await _classify(text, ctx.locale)
                if target is not None:
                    scratch["route"] = target
                    metrics.ROUTER_CHOICES.labels(cfg.id, target, "classifier").inc()
                    _routed_status(target)
                    scratch["go"] = "sub"
                    return {"messages": [HumanMessage(content=text)], "scratch": scratch}
                # not confident → keep the question in history, re-show the menu
                scratch["pending_question"] = True
                scratch.pop("route", None)
                scratch["go"] = "menu"
                return {"messages": [HumanMessage(content=text)], "scratch": scratch}

            # malformed reply / free text in menu mode → re-show the menu (never crash)
            scratch.pop("route", None)
            scratch["go"] = "menu"
            return {"scratch": scratch}

        async def handoff(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            ctx = config["configurable"]["ctx"]
            reply = ask_quick_replies(
                _pick(params.ask_prompt, _DEFAULT_ASK_PROMPT, ctx.locale),
                [{"id": MENU_CHOICE, "label": _pick(params.escape_label, _DEFAULT_ESCAPE_LABEL, ctx.locale)}],
                allow_free_text=True,
            )
            scratch = dict(state.get("scratch", {}))
            choice_id = reply.get("id") if isinstance(reply, dict) else None
            text = (reply.get("text") if isinstance(reply, dict) else None) or ""
            if choice_id == MENU_CHOICE:
                scratch.pop("route", None)  # escape → back to the menu
                scratch["go"] = "menu"
                # high escape rate = users picked the wrong lane = unclear menu labels
                metrics.ROUTER_CHOICES.labels(cfg.id, MENU_CHOICE, "menu").inc()
                return {"scratch": scratch}
            if not text.strip():
                # empty/whitespace question, no escape → re-ask, keep the route sticky
                scratch["go"] = "handoff"
                return {"scratch": scratch}
            # free-text question: a resume carries no HumanMessage (docs/04 §5) —
            # append it here so the routed sub-bot sees what was asked.
            scratch["go"] = "sub"
            return {"messages": [HumanMessage(content=text)], "scratch": scratch}

        def go(state: BotState) -> str:
            """Shared conditional: `scratch["go"]` + the sticky route pick the edge."""
            scratch = state.get("scratch", {})
            route = scratch.get("route")
            if scratch.get("go") == "sub" and route in valid:
                return node_name[route]
            if scratch.get("go") == "handoff":
                return "handoff"
            return "menu"

        edge_map: dict[Hashable, str] = {
            "menu": "menu", "handoff": "handoff", **{n: n for n in node_name.values()}
        }

        b.add_node("menu", menu)
        b.add_node("handoff", handoff)
        if classifier_mode:
            b.add_node("dispatch", dispatch)
            b.set_entry_after_guard("dispatch")
            b.add_conditional_edges("dispatch", go, edge_map)
        else:
            b.set_entry_after_guard("menu")
        b.add_conditional_edges("menu", go, edge_map)

        for target_bot, fragment in subgraph_fragments.items():
            b.add_node(node_name[target_bot], _compile_subgraph(fragment))
            # after a routed answer, back to handoff: next question or the escape
            b.add_edge(node_name[target_bot], "handoff")

        b.add_conditional_edges("handoff", go, edge_map)

    return GraphFragment(flow)
