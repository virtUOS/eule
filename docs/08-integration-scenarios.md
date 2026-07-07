# 08 — Bot integration scenarios (how to plug a backend in)

Adding a bot is **config + a graph fragment + (usually) a backend the fragment calls**.
This doc maps the backends you actually have onto the architecture, and states the
config/development overhead of each. It is the practical companion to the contracts:
`03-registry.md` (config), `04-node-contract.md` (graph + out-of-band identity),
`07-deployment.md` (where services run).

## The one rule that decides everything

The gateway reaches a bot's backend through exactly **one** sanctioned path: **MCP tools
called via `app/mcp/client.py`**, which injects the authenticated `_identity` out of band
on every call (golden rule 2; `04` §7). Anything a bot does that is *not* an MCP tool
call is outside that guarantee. So the first question for any backend is:

> Is it reachable as an MCP server, or can it be made one cheaply?

The exception is a backend that **is itself an OpenAI-compatible chat model** — that
plugs in as a `model_provider`, not as a tool, because the gateway already speaks that
protocol natively (it's how it talks to vLLM).

## The four scenarios

### Scenario 1 — Existing MCP server + a system prompt  ✅ canonical, cheapest with tools
You have an MCP server (RAG, docs search, a database wrapper) and want a bot with a
system prompt that calls it.

- **Config:** one `global.mcp_servers` entry (`transport`, `url`, `timeout_s`, and
  `bearer_token_env` if it needs a token to accept the gateway — see "Server auth"
  below); one `config/bots/<id>.yaml` (`model.provider`, `prompt.system`, `tools`
  allow/deny, `graph`, `guard`, `embedding`).
- **Development:** a graph fragment (see "Fragment shapes"). No new service.
- **Overhead:** low. This is what the whole design optimizes for.

### Scenario 2 — Existing RAG/search system that is NOT MCP-shaped  ⚠️ needs a facade
A REST/gRPC search or RAG API that doesn't speak MCP.

- **Why not call it directly from a node:** you'd re-implement identity injection and
  tool allowlisting per bot — exactly the structural scoping `04` §7 centralizes. Don't.
- **What to do:** put a **thin MCP facade** in `mcp-servers/<name>/` — a small server
  exposing 1–2 typed tools that internally call the RAG API. Then it's Scenario 1.
- **Overhead:** medium. One small service to build/deploy/own. Scales with how simple
  the underlying API already is (a single `search(query)` endpoint is a short adapter).

### Scenario 3 — External OpenAI-compatible endpoint with its own bot behind it  ✅ cheapest overall
A different ecosystem already exposes a specialised assistant behind an OpenAI-compatible
API (its own prompt, its own retrieval).

- **Config:** one `global.model_providers` entry pointing `base_url` at that service
  (+ `api_key_env`). The bot config uses it as `model.provider`, `tools.mcp_servers: []`.
- **Development:** a **passthrough fragment** — call the model, stream tokens, no tool
  loop. Simpler than the tool template.
- **Two things to decide (not blockers):**
  - Our `prompt.system` may be redundant if their backend injects its own — keep ours
    minimal or empty.
  - If their service keeps its own conversation thread, map our `session_id` → their
    thread id in `scratch` (the bot-private state field, `04` §1).
- **Trust boundary:** with no tools of our own, there is **no tool allowlist to bound
  it** — the external service is trusted wholesale, not structurally scoped the way MCP
  tools are. Fine for a vetted internal service; note it for anything less trusted. Its
  output is still untrusted *content* (render as text/sources, never HTML — the widget
  already enforces this).
- **Overhead:** lowest. The gateway can't distinguish this from vLLM.

### Scenario 4 — Migrate an existing (FastAPI) backend into a real MCP server  ⚠️ same class as #2
You own a Python/FastAPI backend and want to fold it into this setup properly.

- **Good news:** the MCP Python SDK's streamable-HTTP transport is an ASGI app, so it
  usually **mounts inside the existing FastAPI app** rather than a rewrite — expose the
  existing business logic as typed `@tool`s.
- **The real work** is authorization: if this backend serves *per-user* data, it must
  enforce **own-data-only** keyed off the incoming `_identity.subject` (`04` §7). That's
  precisely what the mandatory T3 identity-isolation tests (`06` §T3) verify — don't skip
  it for an auth bot.
- **Overhead:** medium; less than #2 when the transport mounts in-place, plus the authz
  work above for auth bots.

## Quick chooser

| You have… | Scenario | New service? | Overhead |
|---|---|---|---|
| An MCP server | 1 | no | low |
| A non-MCP RAG/search API | 2 | yes (thin facade) | medium |
| An OpenAI-compatible bot endpoint | 3 | no | lowest |
| A FastAPI backend to bring in | 4 | mount MCP in it | medium |

## Fragment shapes (the code you write)

Two patterns cover the tool cases (`04` §9 has the skeletons):
- **Fixed retrieve-then-generate (recommended for "simple"):** a node calls the MCP tool
  with the user's message (`emit_status('tool_call', …)`), then an answer node streams the
  model with retrieved context, then `emit_sources(msg.id, …)`. Deterministic; no agentic
  tool-selection to misbehave. **`emit_sources`'s `message_id` MUST be the answer
  message's `.id`** (`04` §3) or the citation binds to the wrong bubble.
- **Tool-calling agent:** the model decides whether/when to call tools. More flexible,
  harder to test. Use when "should I search at all?" is a real per-turn decision.

For Scenario 3, neither: a **passthrough** node that just streams the provider.

**Worked example:** `app/graphs/it_helpdesk.py` + `config/bots/it-helpdesk.yaml` are a
complete reference of the fixed retrieve-then-generate shape — search (`uos_search`) →
fetch top pages (`uos_fetch`) → stream the answer → cite sources, with the model given
no tools (scope = zero) and retrieved content framed as untrusted data. Copy it, point
the config at your MCP server + model provider, and adapt `_parse_results`/`_page_text`
to your server's return shapes.

## Server auth vs. per-user identity (do not conflate)

Two separate concerns, both already supported:
- **`bearer_token_env`** on an `mcp_servers` entry — a static token authenticating *the
  gateway* to the MCP server ("may we connect"). `03`, resolved via
  `registry.resolve_mcp_bearer`.
- **`_identity`** — injected per tool call by `app/mcp/client.py`, says *whose data*
  ("this authenticated user, and only their data"). The MCP server re-validates and
  enforces it. `04` §7. Never a model-visible parameter.

A public docs bot (no personal data) still receives `_identity` on every call; it just
has nothing to scope by. An auth bot's MCP server MUST act on it.

## What every new bot still goes through

Independent of scenario, before a bot is enabled/public:
- `validate-config` passes (checks 1–13, `03`) — provider/servers exist, secrets
  resolve, contrast holds, `graph` is registered.
- Guard enabled for a public bot (check 7 warns otherwise); the guard classifier
  declines out-of-scope input (`06` T4.2).
- Tool allowlist is structural — only allowlisted tools are bound (`06` T4.1), deny
  wins over allow (T4.3).
- Auth bots: T3 identity-isolation (MANDATORY) + T7 conformance harness.
- First public bot: T10-E manual screen-reader audit + published accessibility
  conformance statement (`05` §11) — a human gate, not automatable.
