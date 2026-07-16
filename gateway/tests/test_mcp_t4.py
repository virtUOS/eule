"""T4 (scoping) + T3.2 (model-authored identity) — structural, model-free.

Exercises the MCP identity-injection wrapper and tool allow/deny resolution against a
fake client. Identity travels separately from model arguments (→ `_meta` in the real
transport). The live tool-calling loop (real model + MCP server) is Step 4c;
test_mcp_transport.py exercises the real transport against an in-memory MCP server.
"""

from __future__ import annotations

from typing import Any

from app.mcp.client import McpResult, McpToolSpec, allowed_tool_names, build_mcp_tool, build_tools, mcp_call
from app.runtime.context import Identity, RuntimeContext

from .conftest import make_bot


class _FakeMcpClient:
    def __init__(self) -> None:
        # each entry: (tool_name, arguments, identity)
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []

    async def list_tools(self) -> list[McpToolSpec]:
        return []

    async def call(
        self, tool_name: str, arguments: dict[str, Any], *, identity: dict[str, Any] | None
    ) -> McpResult:
        self.calls.append((tool_name, arguments, identity))
        return McpResult(is_error=False, structured={"ok": True}, text="")


def _ctx(cfg, subject: str = "user-x") -> RuntimeContext:
    return RuntimeContext(
        bot_id=cfg.id,
        config=cfg,
        identity=Identity(authenticated=True, subject=subject, claims={"sub": subject}, roles=["student"]),
        session_id="s1",
        request_id="r1",
        locale="en",
    )


_CREDIT_SCHEMA = {"type": "object", "properties": {"course_id": {"type": "string"}}, "required": ["course_id"]}


def _spec(name: str, desc: str) -> McpToolSpec:
    return McpToolSpec(name=name, description=desc, input_schema=_CREDIT_SCHEMA)


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
        "enrollment.get_my_credits": _spec("enrollment.get_my_credits", "read credits"),
        "enrollment.admin_override": _spec("enrollment.admin_override", "WRITE"),  # exists but not allowed
    }
    tools = build_tools(cfg, _ctx(cfg), _FakeMcpClient(), catalogue)
    names = {t.name for t in tools}
    assert names == {"enrollment.get_my_credits"}
    assert "enrollment.admin_override" not in names


# --- T3.2 — the tool's model-visible signature has no identity parameter ----

def test_t3_2_tool_schema_has_no_identity_param():
    cfg = make_bot()
    tool = build_mcp_tool(
        name="enrollment.get_my_credits", description="x", input_schema=_CREDIT_SCHEMA,
        ctx=_ctx(cfg), client=_FakeMcpClient(),
    )
    args = set(tool.args.keys())
    assert "course_id" in args
    for forbidden in ("_identity", "identity", "subject", "claims", "_meta", "meta"):
        assert forbidden not in args


# --- T3.1 (partial) — the wrapper always injects ctx identity, separate from args -

async def test_wrapper_injects_ctx_identity_separate_from_arguments():
    cfg = make_bot()
    client = _FakeMcpClient()
    ctx = _ctx(cfg, subject="alice")
    # the model tries to smuggle a subject as a normal arg
    await mcp_call(ctx, client, "enrollment.get_my_credits", {"subject": "bob", "course_id": "CS101"})
    tool_name, arguments, identity = client.calls[-1]
    assert tool_name == "enrollment.get_my_credits"
    # identity comes from ctx and travels in its OWN channel (→ _meta), never arguments
    assert identity == {"subject": "alice", "claims": {"sub": "alice"}}
    # the model's smuggled value stays in arguments (ignored by the server for authz)
    assert arguments == {"subject": "bob", "course_id": "CS101"}
    assert "subject" not in identity or identity["subject"] == "alice"


async def test_build_mcp_tool_run_returns_structured_or_text():
    cfg = make_bot()
    tool = build_mcp_tool(
        name="t", description="d", input_schema=_CREDIT_SCHEMA, ctx=_ctx(cfg), client=_FakeMcpClient(),
    )
    out = await tool.ainvoke({"course_id": "CS101"})
    assert out == {"ok": True}  # structured preferred
