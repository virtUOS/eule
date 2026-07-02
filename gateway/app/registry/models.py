"""Pydantic v2 config models for the bot registry (docs/03-registry.md).

`extra="forbid"` on the top-level global and per-bot models is deliberate: it fails
boot on stale OLD-spec fields (`form`, `openai_api`, `surface`, `primary_color`,
`color_primary`, …) instead of silently ignoring them. Golden rule 4: fail fast.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Overridable subset — identical nesting in global `defaults` and per-bot config
# (docs/03 §"Config shape"). Deep-merged by the loader before validation.
# ---------------------------------------------------------------------------


class RateTier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests_per_min: int | None = None
    requests_per_day: int | None = None


class RateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anonymous: RateTier | None = None
    authenticated: RateTier | None = None


class Guard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: str | None = None
    on_out_of_scope: Literal["decline"] | None = None


class Greeting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["client_initiated", "bot_greeting"] = "client_initiated"


class Defaults(BaseModel):
    """Global defaults; per-bot overrides must match this shape (check 8)."""

    model_config = ConfigDict(extra="forbid")
    session_ttl_s: int = 1800
    max_message_chars: int = 4000
    history_max_turns: int = 20
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    guard: Guard = Field(default_factory=Guard)
    greeting: Greeting = Field(default_factory=Greeting)


# ---------------------------------------------------------------------------
# Global-only config (NOT per-bot overridable)
# ---------------------------------------------------------------------------


class ModelProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    api_key_env: str
    default_model: str | None = None
    timeout_s: int = 60
    max_retries: int = 2


class McpServer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transport: Literal["stdio", "streamable-http"]
    url: str | None = None
    timeout_s: int = 20
    # Static bearer token to authenticate the GATEWAY to this MCP server (secret
    # referenced by env name, never a value — golden rule 6). This is orthogonal to
    # the per-call `_identity` the gateway injects into every tool call (docs/04 §7):
    # that says "whose data"; this says "is the gateway allowed to connect at all".
    bearer_token_env: str | None = None


class AuthCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    jwks_url: str
    audience: str
    leeway_s: int = 30


class Streaming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heartbeat_s: int = 15


class ThemeTokens(BaseModel):
    """Deployment theme token block. Token maps are open (`--*` keys)."""

    model_config = ConfigDict(extra="forbid")
    dark_mode: Literal["auto", "light", "dark"] = "auto"
    light: dict[str, str]
    dark: dict[str, str]
    radius: dict[str, str] = Field(default_factory=dict)


class GlobalCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    model_providers: dict[str, ModelProvider]
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict)
    auth: AuthCfg | None = None
    defaults: Defaults = Field(default_factory=Defaults)
    streaming: Streaming = Field(default_factory=Streaming)
    theme: ThemeTokens


# ---------------------------------------------------------------------------
# Per-bot config
# ---------------------------------------------------------------------------


class ModelCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    temperature: float | None = None
    max_tokens: int | None = None


class PromptCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str = ""


class IdentityCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_claim: str = "sub"
    required_roles: list[str] = Field(default_factory=list)


class ToolsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mcp_servers: list[str] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class EmbeddingCfg(BaseModel):
    # mode ∈ {launcher, inline, standalone}. `overlay` is DEAD (was inline|overlay);
    # Pydantic rejects it → fails boot. `launcher` is its replacement.
    model_config = ConfigDict(extra="forbid")
    mode: Literal["launcher", "inline", "standalone"] = "launcher"
    allowed_origins: list[str] = Field(default_factory=list)


class StarterReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    query: str


class RouteTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot: str
    label: str


class RoutesCfg(BaseModel):
    # `mode` kept as a plain str so an unsupported value (e.g. "classifier") is
    # rejected by validation check 12 with a clear message, not a Pydantic error.
    model_config = ConfigDict(extra="forbid")
    mode: str = "menu"
    sticky: bool = True
    targets: list[RouteTarget] = Field(default_factory=list)


class ThemeOverride(BaseModel):
    """Per-bot theme override: partial token maps keyed by the same `--*` names,
    deep-merged over the deployment theme. (No `color_primary`/`color_on_primary`.)"""

    model_config = ConfigDict(extra="forbid")
    dark_mode: Literal["auto", "light", "dark"] | None = None
    light: dict[str, str] = Field(default_factory=dict)
    dark: dict[str, str] = Field(default_factory=dict)
    radius: dict[str, str] = Field(default_factory=dict)


class AuditCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False


class Observability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log_message_content: bool = False
    audit: AuditCfg = Field(default_factory=AuditCfg)


class BotCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    id: str
    name: str
    description: str | None = None
    enabled: bool = True

    model: ModelCfg
    prompt: PromptCfg = Field(default_factory=PromptCfg)

    # Which code-defined graph fragment this bot uses (docs/03: "config only references
    # which graph a bot uses" — graphs themselves are never data). Resolved against the
    # fragment registry in app/graphs/registry.py; validated at boot (check 13).
    graph: str = "echo"

    requires_auth: bool = False
    identity: IdentityCfg | None = None

    tools: ToolsCfg = Field(default_factory=ToolsCfg)

    # Overridable subset — the loader resolves these via deep-merge with global
    # `defaults` before construction, so they are always present here.
    session_ttl_s: int
    max_message_chars: int
    history_max_turns: int
    rate_limit: RateLimit
    guard: Guard
    greeting: Greeting

    embedding: EmbeddingCfg = Field(default_factory=EmbeddingCfg)
    starter_replies: dict[str, list[StarterReply]] = Field(default_factory=dict)
    theme: ThemeOverride | None = None
    routes: RoutesCfg | None = None
    observability: Observability = Field(default_factory=Observability)
