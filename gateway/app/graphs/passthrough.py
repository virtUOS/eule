"""Stock `passthrough` fragment (docs/08 Scenario 3; BUILD_PLAN step 9).

Config-only bot shape: stream the bot's model provider with the session history —
no tools, no loop. The provider may be a plain model (vLLM) or a whole specialised
bot behind an OpenAI-compatible endpoint (e.g. askUOS); the gateway cannot tell
them apart. `status("thinking")` covers the dead air of providers that retrieve
before emitting tokens.

Selected via `graph: "passthrough"`. Takes no `graph_params` (check 14 rejects any).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from pydantic import BaseModel, ConfigDict

from .emit import emit_status
from .model import astream_message, build_chat_model
from .skeleton import BotGraphBuilder, BotState, GraphFragment

if TYPE_CHECKING:
    from ..registry.models import BotCfg
    from ..registry.registry import Registry


class PassthroughParams(BaseModel):
    """No parameters. extra="forbid" makes any provided key a check-14 boot error."""

    model_config = ConfigDict(extra="forbid")


def build_passthrough_fragment(
    cfg: "BotCfg",
    registry: "Registry",
    *,
    answer_model: BaseChatModel | None = None,
) -> GraphFragment:
    """`answer_model` is a test seam; production resolves the provider from config."""
    PassthroughParams(**cfg.graph_params)  # boot-validated (check 14); cheap re-assert
    model = answer_model or build_chat_model(registry.resolve_provider(cfg))
    system = cfg.prompt.system  # optional — a Scenario-3 backend injects its own

    def flow(b: BotGraphBuilder) -> None:
        async def respond(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            emit_status("thinking", "…")
            prompt = ([SystemMessage(system)] if system else []) + list(state["messages"])
            full = await astream_message(model, prompt)
            return {"messages": [full]}

        b.add_node("respond", respond)
        b.set_entry_after_guard("respond")
        b.add_edge("respond", END)

    return GraphFragment(flow)
