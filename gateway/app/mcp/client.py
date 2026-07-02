"""MCP tool calling with out-of-band identity injection (docs/04 §7, SECURITY-CRITICAL).

The single rule this module exists to enforce (golden rule 2):
- Identity-bearing data is NEVER in a tool's model-visible signature, so the model
  cannot supply someone else's id.
- EVERY MCP call goes through `mcp_call`, which attaches the trusted identity from
  RuntimeContext. The MCP server re-validates it and enforces "own data only".

Identity travels via MCP's **`_meta` request field**, NOT as a tool argument (verified:
a FastMCP server silently drops an extra `_identity` argument, so the arg-merge approach
would make identity vanish en route — a security failure). `_meta` is transport metadata,
structurally outside the tool's `inputSchema`, so the model can neither author nor name
it. The concrete transport (`StreamableHttpMcpClient`) routes `identity` to `_meta`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool

from ..registry.models import BotCfg
from ..runtime.context import RuntimeContext


@dataclass(frozen=True)
class McpToolSpec:
    """A tool as discovered from an MCP server (`tools/list`)."""

    name: str
    description: str
    input_schema: dict[str, Any]  # raw JSON Schema; consumable directly as args_schema


@dataclass(frozen=True)
class McpResult:
    """Normalized tool-call result."""

    is_error: bool
    structured: Any  # structuredContent if the tool returned it, else None
    text: str  # concatenated text content blocks (untrusted — render as data, never HTML)


class McpClient(Protocol):
    async def list_tools(self) -> list[McpToolSpec]: ...

    # `identity` is passed separately from model `arguments` so the concrete client can
    # route it to `_meta` — it must never be merged into the tool arguments.
    async def call(
        self, tool_name: str, arguments: dict[str, Any], *, identity: dict[str, Any] | None
    ) -> McpResult: ...


def allowed_tool_names(cfg: BotCfg) -> list[str]:
    """Effective tool allowlist: `allow` minus `deny` (denylist wins — docs/04, T4.3).
    A tool listed in both allow and deny is unavailable."""
    deny = set(cfg.tools.deny)
    return [name for name in cfg.tools.allow if name not in deny]


async def mcp_call(
    ctx: RuntimeContext, client: McpClient, tool_name: str, **model_args: Any
) -> McpResult:
    """The ONE wrapper for every MCP call. Identity comes from ctx (→ `_meta`), never
    the model; the model's `model_args` become the tool `arguments` verbatim. Even if the
    model smuggles a `subject`/`_identity` key, it lands in `arguments`, which the server
    ignores for authz — the server trusts only `_meta`."""
    return await client.call(
        tool_name,
        arguments=dict(model_args),
        identity={"subject": ctx.identity.subject, "claims": ctx.identity.claims},
    )


def build_mcp_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    ctx: RuntimeContext,
    client: McpClient,
) -> BaseTool:
    """Bind one MCP tool for the model. The model-visible schema is EXACTLY the tool's
    declared `input_schema` (JSON Schema) — it contains no identity field."""

    async def _run(**model_args: Any) -> Any:
        result = await mcp_call(ctx, client, name, **model_args)
        # Prefer structured output; fall back to text. Tool output is UNTRUSTED content.
        return result.structured if result.structured is not None else result.text

    return StructuredTool.from_function(
        coroutine=_run, name=name, description=description, args_schema=input_schema
    )


def build_tools(
    cfg: BotCfg,
    ctx: RuntimeContext,
    client: McpClient,
    specs: dict[str, McpToolSpec],
) -> list[BaseTool]:
    """Bind every tool in the bot's effective allowlist. `specs` maps a tool name to its
    discovered spec. A tool outside the allowlist is never bound — structural scoping
    (T4.1): the graph literally has no way to call it."""
    tools: list[BaseTool] = []
    for tool_name in allowed_tool_names(cfg):
        spec = specs.get(tool_name)
        if spec is None:
            continue
        tools.append(
            build_mcp_tool(
                name=spec.name, description=spec.description,
                input_schema=spec.input_schema, ctx=ctx, client=client,
            )
        )
    return tools
