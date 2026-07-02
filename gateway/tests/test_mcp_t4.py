"""T4 (scoping) + T3.2 (model-authored identity) — structural, model-free.

Exercises the MCP identity-injection wrapper and tool allow/deny resolution. The live
tool-calling loop (real model + MCP server) is Step 4c.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.mcp.client import allowed_tool_names, build_mcp_tool, build_tools, mcp_call
from app.runtime.context import Identity, RuntimeContext

from .conftest import make_bot


class _FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        return {"ok": True}


def _ctx(cfg, subject: str = "user-x") -> RuntimeContext:
    return RuntimeContext(
        bot_id=cfg.id,
        config=cfg,
        identity=Identity(authenticated=True, subject=subject, claims={"sub": subject}, roles=["student"]),
        session_id="s1",
        request_id="r1",
        locale="en",
    )


class CreditArgs(BaseModel):
    course_id: str


# --- T4.3 — denylist precedence --------------------------------------------

def test_t4_3_deny_beats_allow():
    cfg = make_bot(
        tools={"mcp_servers": ["enrollment"], "allow": ["a", "b", "admin"], "deny": ["admin"]},
    )
    assert allowed_tool_names(cfg) == ["a", "b"]  # admin removed despite being allowed


# --- T4.1 — structural read-only scoping -----------------------------------

def test_t4_1_only_allowlisted_tools_are_bound():
    # a read-only bot lists only read tools; write tools exist in the catalogue but are
    # never bound, so the graph structurally cannot call them.
    cfg = make_bot(tools={"mcp_servers": ["enrollment"], "allow": ["enrollment.get_my_credits"], "deny": []})
    catalogue = {
        "enrollment.get_my_credits": ("read credits", CreditArgs),
        "enrollment.admin_override": ("WRITE", CreditArgs),  # exists but not allowed
    }
    tools = build_tools(cfg, _ctx(cfg), _FakeMcpClient(), catalogue)
    names = {t.name for t in tools}
    assert names == {"enrollment.get_my_credits"}
    assert "enrollment.admin_override" not in names


# --- T3.2 — the tool's model-visible signature has no identity parameter ----

def test_t3_2_tool_schema_has_no_identity_param():
    cfg = make_bot()
    tool = build_mcp_tool(
        name="enrollment.get_my_credits", description="x", args_schema=CreditArgs,
        ctx=_ctx(cfg), client=_FakeMcpClient(),
    )
    args = set(tool.args.keys())
    assert "course_id" in args
    for forbidden in ("_identity", "identity", "subject", "claims"):
        assert forbidden not in args


# --- T3.1 (partial) — the wrapper always injects ctx identity, never the model's -

async def test_wrapper_injects_ctx_identity_not_model_supplied():
    cfg = make_bot()
    client = _FakeMcpClient()
    ctx = _ctx(cfg, subject="alice")
    # even if the model tries to smuggle a subject as a normal arg, _identity is ctx's
    await mcp_call(ctx, client, "enrollment.get_my_credits", subject="bob", course_id="CS101")
    tool_name, kwargs = client.calls[-1]
    assert tool_name == "enrollment.get_my_credits"
    assert kwargs["_identity"] == {"subject": "alice", "claims": {"sub": "alice"}}
    # the model's smuggled value is passed through as an ordinary arg, NOT as identity;
    # the MCP server trusts only _identity
    assert kwargs["subject"] == "bob"
    assert kwargs["course_id"] == "CS101"
