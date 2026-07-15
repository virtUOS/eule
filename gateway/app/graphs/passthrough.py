"""Stock `passthrough` fragment (docs/08 Scenario 3; BUILD_PLAN steps 9 + 9a).

Config-only bot shape: stream the bot's model provider with the session history —
no tools, no loop. The provider may be a plain model (vLLM) or a whole specialised
bot behind an OpenAI-compatible endpoint (e.g. askUOS); the gateway cannot tell
them apart. `status("thinking")` covers the dead air of providers that retrieve
before emitting tokens.

History is STATELESS toward the provider (9a decision): the gateway sends its own
session history each turn — standard OpenAI, no coupling to a backend's custom
thread state — capped at the bot's `history_max_turns`.

Locale forwarding (9a decision, generic): some Scenario-3 backends take a
non-standard request-body field for the answer language (askUOS: `language` =
"Deutsch"/"English"). `graph_params.locale_body_field` + `locale_values` map the
request locale (`ctx.locale`, from the widget) onto that field via `extra_body`;
an unmapped or absent locale omits the field (the backend's own default applies).

Selected via `graph: "passthrough"`; params validated at boot (check 14).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from pydantic import BaseModel, ConfigDict, Field

from .emit import emit_status
from .model import astream_message, build_chat_model
from .skeleton import BotGraphBuilder, BotState, GraphFragment

if TYPE_CHECKING:
    from ..registry.models import BotCfg
    from ..registry.registry import Registry


class PassthroughParams(BaseModel):
    """Per-bot `graph_params` for `graph: "passthrough"` (validated at boot, check 14)."""

    model_config = ConfigDict(extra="forbid")
    # Non-standard provider request-body field carrying the answer language
    # (e.g. askUOS: "language"). None = forward nothing.
    locale_body_field: str | None = None
    # Base-language → provider value (e.g. {de: "Deutsch", en: "English"}).
    # An unmapped locale omits the field (provider default applies).
    locale_values: dict[str, str] = Field(default_factory=dict)


def _capped_history(messages: list[BaseMessage], max_turns: int) -> list[BaseMessage]:
    """Bound the stateless per-turn payload: keep the last `max_turns` exchanges
    (~2 messages per turn). The full history stays in the gateway checkpointer."""
    return list(messages)[-2 * max_turns :]


def _locale_kwargs(params: PassthroughParams, locale: str | None) -> dict[str, Any]:
    if not params.locale_body_field or not locale:
        return {}
    value = params.locale_values.get(locale.split("-")[0].lower())
    if value is None:
        return {}
    return {"extra_body": {params.locale_body_field: value}}


def build_passthrough_fragment(
    cfg: "BotCfg",
    registry: "Registry",
    *,
    answer_model: BaseChatModel | None = None,
) -> GraphFragment:
    """`answer_model` is a test seam; production resolves the provider from config."""
    params = PassthroughParams(**cfg.graph_params)  # boot-validated (check 14); re-assert
    model = answer_model or build_chat_model(registry.resolve_provider(cfg))
    system = cfg.prompt.system  # optional — a Scenario-3 backend injects its own
    max_turns = cfg.history_max_turns

    def flow(b: BotGraphBuilder) -> None:
        async def respond(state: BotState, config: RunnableConfig) -> dict[str, Any]:
            ctx = config["configurable"]["ctx"]
            emit_status("thinking", "…")
            history = _capped_history(state["messages"], max_turns)
            prompt = ([SystemMessage(system)] if system else []) + history
            full = await astream_message(model, prompt, **_locale_kwargs(params, ctx.locale))
            return {"messages": [full]}

        b.add_node("respond", respond)
        b.set_entry_after_guard("respond")
        b.add_edge("respond", END)

    return GraphFragment(flow)
