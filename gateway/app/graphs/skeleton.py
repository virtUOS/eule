"""Shared graph skeleton + factory (docs/04 §6).

The gateway drives every bot identically; all variation lives in the fragment (the
middle region). The checkpointer is wired in `build_bot_graph` ONLY.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Callable, Hashable, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ..runtime import metrics
from .emit import emit_status


class BotState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    turn_input: dict[str, Any]  # normalized input for this turn (docs/04 §5)
    scratch: dict[str, Any]  # bot-private, not part of the external contract


class BotGraphBuilder:
    """Thin wrapper over StateGraph that lets a fragment declare its entry node
    (`set_entry_after_guard`) without knowing whether a guard precedes it."""

    def __init__(self) -> None:
        self.g: StateGraph[Any, Any, Any, Any] = StateGraph(BotState)
        self._entry: str | None = None

    def add_node(self, name: str, node: Any) -> None:
        self.g.add_node(name, node)

    def add_edge(self, src: str, dst: str) -> None:
        self.g.add_edge(src, dst)

    def add_conditional_edges(self, src: str, cond: Any, mapping: dict[Hashable, str]) -> None:
        self.g.add_conditional_edges(src, cond, mapping)

    def set_entry_after_guard(self, name: str) -> None:
        self._entry = name

    @property
    def entry(self) -> str:
        if self._entry is None:
            raise ValueError("fragment did not call set_entry_after_guard(...)")
        return self._entry


class GraphFragment:
    """A bot's middle region: a function that populates a BotGraphBuilder."""

    def __init__(self, flow: Callable[[BotGraphBuilder], None]) -> None:
        self.flow = flow


async def _stream_canned(text: str, history: list[BaseMessage]) -> AIMessage:
    """Emit `text` through the sanctioned model-streaming path (no real model yet).
    Used by the decline node and the echo stub."""
    model = GenericFakeChatModel(messages=iter([AIMessage(content=text)]))
    chunks = [c async for c in model.astream(history)]
    full = chunks[0]
    for c in chunks[1:]:
        full = full + c
    return AIMessage(content=full.content or text, id=full.id)


def make_guard_node(cfg: Any, model: BaseChatModel) -> Callable[..., Any]:
    """Cheap-model scope classifier (docs/04 §6). `model` is a NON-answer-facing chat
    model call — invoked with `tags=[TAG_NOSTREAM]` so its own "in_scope"/"out_of_scope"
    tokens are excluded from LangGraph's `stream_mode="messages"` and never leak into the
    client's `text` stream (any model call inside any node is otherwise picked up there,
    regardless of which node produced it — verified: this is not hypothetical)."""

    scope = f"'{cfg.name}'" + (f": {cfg.description}" if cfg.description else "")
    system = SystemMessage(
        f"You are a strict scope classifier for the assistant {scope}. Given the "
        "user's latest message (and any recent context), reply with EXACTLY one "
        "word: 'in_scope' if it is something this assistant should help with, or "
        "'out_of_scope' otherwise. No punctuation, no explanation."
    )

    async def guard(state: BotState, config: RunnableConfig) -> dict[str, Any]:
        emit_status("thinking", "…")
        # Classify ONLY the latest user message, not the whole history — a bounded,
        # injection-resistant input (history can otherwise be seeded to steer the
        # classifier). Greeting/empty turn → nothing to classify → in_scope.
        latest = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
        )
        if latest is None:
            return {"scratch": {**state.get("scratch", {}), "guard": "in_scope"}}
        result = await model.ainvoke([system, latest], config={"tags": [TAG_NOSTREAM]})
        # Match the LEADING token only (the prompt asks for exactly one word). This
        # deliberately FAILS OPEN (defaults to in_scope) on any non-conforming output:
        # the guard is defense-in-depth — structural tool scope (golden rule 3) is the
        # real enforcement, so an over-eager decline would harm more than a rare miss.
        leading = re.split(r"[^a-z_]+", str(result.content).strip().lower(), maxsplit=1)[0]
        verdict = "out_of_scope" if leading == "out_of_scope" else "in_scope"
        metrics.GUARD_VERDICTS.labels(cfg.id, verdict).inc()  # out-of-scope rate (step 11)
        return {"scratch": {**state.get("scratch", {}), "guard": verdict}}

    return guard


def guard_route(state: BotState) -> str:
    return str(state.get("scratch", {}).get("guard", "in_scope"))


def make_decline_node(cfg: Any) -> Callable[..., Any]:
    async def decline(state: BotState, config: RunnableConfig) -> dict[str, Any]:
        msg = await _stream_canned(
            "Sorry, that's outside what I can help with here.", state["messages"]
        )
        return {"messages": [msg]}

    return decline


def build_bot_graph(
    cfg: Any,
    tools: list[Any],
    fragment: GraphFragment,
    checkpointer: Any,
    guard_model: BaseChatModel | None = None,
) -> Any:
    """Build the outer skeleton, attach the fragment, compile with the checkpointer.
    This is the ONLY place the checkpointer is wired. `guard_model` is required iff
    `cfg.guard.enabled` (validation check 6 guarantees a provider is configured; the
    caller resolves it to a real/fake chat model — see graphs/factory.py)."""
    b = BotGraphBuilder()
    guarded = cfg.guard.enabled
    if guarded:
        if guard_model is None:
            raise ValueError(f"bot '{cfg.id}' has guard.enabled but no guard_model was built")
        b.add_node("guard", make_guard_node(cfg, guard_model))
        b.add_node("decline", make_decline_node(cfg))

    fragment.flow(b)
    entry = b.entry

    if guarded:
        b.add_edge(START, "guard")
        b.add_conditional_edges(
            "guard", guard_route, {"in_scope": entry, "out_of_scope": "decline"}
        )
        b.add_edge("decline", END)
    else:
        b.add_edge(START, entry)

    return b.g.compile(checkpointer=checkpointer)
