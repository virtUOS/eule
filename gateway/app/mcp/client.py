"""MCP tool calling with out-of-band identity injection (docs/04 §7, SECURITY-CRITICAL).

The single rule this module exists to enforce (golden rule 2):
- Identity-bearing arguments are NEVER in a tool's model-visible signature, so the model
  cannot supply someone else's id.
- EVERY MCP call goes through `mcp_call`, which attaches `_identity` from the trusted
  RuntimeContext. The MCP server re-validates it and enforces "own data only".

The concrete streamable-HTTP transport (the official MCP SDK client) is wired in Step 4c;
this module is written against an `McpClient` protocol so the identity discipline is
testable without a live server.
"""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from ..registry.models import BotCfg
from ..runtime.context import RuntimeContext


class McpClient(Protocol):
    async def call(self, tool_name: str, **kwargs: Any) -> Any: ...


def allowed_tool_names(cfg: BotCfg) -> list[str]:
    """Effective tool allowlist: `allow` minus `deny` (denylist wins — docs/04, T4.3).
    A tool listed in both allow and deny is unavailable."""
    deny = set(cfg.tools.deny)
    return [name for name in cfg.tools.allow if name not in deny]


async def mcp_call(
    ctx: RuntimeContext, client: McpClient, tool_name: str, **model_args: Any
) -> Any:
    """The ONE wrapper for every MCP call. `_identity` comes from ctx, never the model;
    any identity-shaped value in `model_args` is irrelevant — the server trusts only
    `_identity`."""
    return await client.call(
        tool_name,
        _identity={"subject": ctx.identity.subject, "claims": ctx.identity.claims},
        **model_args,
    )


def build_mcp_tool(
    *,
    name: str,
    description: str,
    args_schema: type[BaseModel],
    ctx: RuntimeContext,
    client: McpClient,
) -> BaseTool:
    """Bind one MCP tool for the model. The model-visible schema is EXACTLY `args_schema`
    (the tool's declared inputs) — it contains no identity parameter."""

    async def _run(**model_args: Any) -> Any:
        return await mcp_call(ctx, client, name, **model_args)

    return StructuredTool.from_function(
        coroutine=_run, name=name, description=description, args_schema=args_schema
    )


def build_tools(
    cfg: BotCfg,
    ctx: RuntimeContext,
    client: McpClient,
    schemas: dict[str, tuple[str, type[BaseModel]]],
) -> list[BaseTool]:
    """Bind every tool in the bot's effective allowlist. `schemas` maps a tool name to
    its (description, args_schema) as discovered from the MCP server. A tool outside the
    allowlist is never bound — structural scoping (T4.1): the graph literally has no way
    to call it."""
    tools: list[BaseTool] = []
    for tool_name in allowed_tool_names(cfg):
        if tool_name not in schemas:
            continue
        description, args_schema = schemas[tool_name]
        tools.append(
            build_mcp_tool(
                name=tool_name, description=description, args_schema=args_schema,
                ctx=ctx, client=client,
            )
        )
    return tools
