"""Real OpenAI-compatible chat model client (docs/00 tech stack: "OpenAI-compatible
endpoint (self-hosted vLLM/LiteLLM). Use an OpenAI-compatible client; base_url from
config."). `ChatOpenAI` pointed at any OpenAI-compatible base_url — this is exactly as
correct for self-hosted vLLM/LiteLLM as it is for a third-party service that already
embodies a specialized bot (docs/08 §Scenario 3): the gateway cannot tell them apart.
"""

from __future__ import annotations

from typing import Any

import httpx
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ..registry.registry import ResolvedProvider


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
