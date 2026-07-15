"""Real OpenAI-compatible chat model client (docs/00 tech stack: "OpenAI-compatible
endpoint (self-hosted vLLM/LiteLLM). Use an OpenAI-compatible client; base_url from
config."). `ChatOpenAI` pointed at any OpenAI-compatible base_url — this is exactly as
correct for self-hosted vLLM/LiteLLM as it is for a third-party service that already
embodies a specialized bot (docs/08 §Scenario 3): the gateway cannot tell them apart.
"""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ..registry.registry import ResolvedProvider


async def astream_message(
    model: BaseChatModel, messages: list[BaseMessage], **kwargs: Any
) -> AIMessage:
    """Stream a model to a single AIMessage. Streaming (not ainvoke) so LangGraph's
    `stream_mode="messages"` observes each token as it is produced. The returned `.id`
    is the run id the `text` events were tagged with — pass it to `emit_sources`.

    `kwargs` pass through to the provider call — e.g. `extra_body={...}` reaches an
    OpenAI-compatible endpoint's request body verbatim (SDK-merged), which is how a
    Scenario-3 backend's non-standard per-request fields are supplied (docs/08)."""
    chunks = [c async for c in model.astream(messages, **kwargs)]
    if not chunks:
        return AIMessage(content="")
    full = chunks[0]
    for c in chunks[1:]:
        full = full + c
    return AIMessage(content=full.content, id=full.id)


def build_chat_model(
    provider: ResolvedProvider, *, http_async_client: httpx.AsyncClient | None = None
) -> ChatOpenAI:
    """`http_async_client` is a test seam (inject a client on a `httpx.MockTransport`
    to prove streaming end-to-end with no real network) — production callers omit it."""
    if not provider.default_model:
        raise ValueError(
            f"model provider '{provider.name}' has no default_model configured "
            f"(global.model_providers.{provider.name}.default_model)"
        )
    kwargs: dict[str, Any] = {}
    if http_async_client is not None:
        kwargs["http_async_client"] = http_async_client
    return ChatOpenAI(
        base_url=provider.base_url,
        api_key=SecretStr(provider.api_key),
        model=provider.default_model,
        timeout=provider.timeout_s,
        max_retries=provider.max_retries,
        streaming=True,
        **kwargs,
    )
