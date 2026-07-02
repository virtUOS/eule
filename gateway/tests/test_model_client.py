"""Prereq D — real OpenAI-compatible model client. Verifies wiring only (base_url,
key, model, timeout, retries, streaming) — the streaming mechanics themselves are
already proven against BaseChatModel generically via the fake model in test_protocol_t1.
"""

from __future__ import annotations

import pytest

from app.graphs.model import build_chat_model
from app.registry.registry import ResolvedProvider


def _provider(**over: object) -> ResolvedProvider:
    base = dict(
        name="default", base_url="https://vllm.example/v1", api_key="secret-key",
        default_model="llama-3.3-70b-instruct", timeout_s=45, max_retries=3,
    )
    base.update(over)
    return ResolvedProvider(**base)  # type: ignore[arg-type]


def test_build_chat_model_wires_config_through():
    model = build_chat_model(_provider())
    assert model.openai_api_base == "https://vllm.example/v1"
    assert model.model_name == "llama-3.3-70b-instruct"
    assert model.request_timeout == 45.0
    assert model.max_retries == 3
    assert model.streaming is True
    assert model.openai_api_key is not None
    assert model.openai_api_key.get_secret_value() == "secret-key"


def test_build_chat_model_requires_a_default_model():
    with pytest.raises(ValueError, match="default_model"):
        build_chat_model(_provider(default_model=None))
