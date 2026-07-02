"""Echo stub bot (BUILD_PLAN Step 1). Streams the user's text back through the
model-node path so the full `text` event vocabulary is exercised without a real model."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from .skeleton import BotGraphBuilder, BotState, GraphFragment, _stream_canned


def _last_user_text(state: BotState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


def build_echo_fragment() -> GraphFragment:
    def flow(b: BotGraphBuilder) -> None:
        async def echo(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            text = _last_user_text(state)
            reply = f"You said: {text}" if text else "Hello! How can I help?"
            msg: AIMessage = await _stream_canned(reply, state["messages"])
            return {"messages": [msg]}

        b.add_node("echo", echo)
        b.set_entry_after_guard("echo")
        b.add_edge("echo", END)

    return GraphFragment(flow)
