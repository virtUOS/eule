"""Shared graph skeleton + factory (docs/04 §6).

The gateway drives every bot identically; all variation lives in the fragment (the
middle region). The checkpointer is wired in `build_bot_graph` ONLY.
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, Hashable, TypedDict

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

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


def make_guard_node(cfg: Any) -> Callable[..., Any]:
    """Guard scaffolding (docs/04 §6). Step 1 stub: always in-scope; the real cheap
    classifier lands in Step 4. Kept so guarded bots compile."""

    async def guard(state: BotState, config: RunnableConfig) -> dict[str, Any]:
        emit_status("thinking", "…")
        return {"scratch": {**state.get("scratch", {}), "guard": "in_scope"}}

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
    cfg: Any, tools: list[Any], fragment: GraphFragment, checkpointer: Any
) -> Any:
    """Build the outer skeleton, attach the fragment, compile with the checkpointer.
    This is the ONLY place the checkpointer is wired."""
    b = BotGraphBuilder()
    guarded = cfg.guard.enabled
    if guarded:
        b.add_node("guard", make_guard_node(cfg))
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
