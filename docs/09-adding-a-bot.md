# 09 — Adding a bot

A bot is **a config file + a graph fragment + one registry entry** (plus, usually, an
MCP server that runs elsewhere). The gateway drives every bot identically, so you never
touch session handling, auth, SSE, the checkpointer, event translation, interrupt
correlation, or the guard/decline scaffolding — those are the skeleton's job
(`docs/04-node-contract.md` §9). You write only the middle.

Worked reference throughout: **`it-helpdesk`** — `config/bots/it-helpdesk.yaml` +
`gateway/app/graphs/it_helpdesk.py`. Copy it.

## Step 0 — Pick the integration scenario

Decide how the backend connects (`docs/08-integration-scenarios.md`): an existing MCP
server (canonical), a non-MCP API behind a thin MCP facade, an OpenAI-compatible endpoint
(no tools — a passthrough), or a FastAPI backend you mount MCP into. This decides whether
you need an `mcp_servers` entry and which fragment shape to write.

## Step 1 — Register the MCP server (if the bot uses tools)

In `config/global.yaml` under `mcp_servers` (`docs/03-registry.md`):

```yaml
mcp_servers:
  my-backend:
    transport: "streamable-http"
    url: "https://mcp-my-backend.example.org/mcp"
    timeout_s: 30
    bearer_token_env: "MY_BACKEND_MCP_TOKEN"   # omit if the server needs no token
```

Add the token name to `.env` / `.env.example` and your CI/deploy env. Two separate
concerns, don't conflate them (`docs/04` §7): `bearer_token_env` authenticates the
**gateway to the server** ("may we connect"); per-user **identity** is injected per call
via MCP `_meta` ("whose data") — you get that for free through `mcp_call`.

## Step 2 — Write the bot config

`config/bots/<id>.yaml` (filename stem MUST equal `id`). Full schema in `docs/03`; the
fields that matter:

```yaml
version: 1
id: "my-bot"
name: "My Bot"
description: "One line — also used by the guard classifier to judge scope."
enabled: true

graph: "my-bot"                 # which fragment (Step 4). Checked at boot (check 13).

model:
  provider: "fast-small"        # a name from global.model_providers

prompt:
  system: |                     # your system prompt

requires_auth: false            # true → add `identity:` + a Keycloak role; see §Auth
tools:
  mcp_servers: ["my-backend"]   # [] for a no-tools bot
  allow: ["tool_a", "tool_b"]   # effective set = allow − deny (deny wins)
  deny:  []

guard: { enabled: true, provider: "fast-small" }   # REQUIRED on for a public bot (check 7 warns)
greeting: { mode: "client_initiated" }             # or bot_greeting

embedding:
  mode: "launcher"              # launcher | inline | standalone
  allowed_origins: ["https://www.uni-osnabrueck.de"]   # sites allowed to embed/call

starter_replies:                # persistent suggestion chips (send a normal message),
  de: [ { label: "…", query: "…" } ]                   # NOT protocol quick_replies
  en: [ { label: "…", query: "…" } ]
```

## Step 3 — Write the graph fragment

`gateway/app/graphs/<id>.py`. A fragment is `GraphFragment(flow)` where `flow` populates
a `BotGraphBuilder`: add your nodes, declare the entry with `set_entry_after_guard(...)`
(the skeleton wires guard→entry or START→entry for you), and edge your last node to `END`.

The three contracts every node obeys (`docs/04` §§1–3):

- **State** (`BotState`): `messages` (the persisted conversation — return
  `{"messages": [...]}` to append), `turn_input` (this turn, normalized), `scratch`
  (bot-private; keep turn-specific junk OUT of long-lived state).
- **Runtime context**: read identity/config from `config["configurable"]["ctx"]` at call
  time — NEVER from closure capture (the compiled graph is cached and shared across
  users/requests). Identity is never in state, prompt, or a tool arg.
- **Emission helpers** (`app/graphs/emit.py`) are the only sanctioned event producers:
  `emit_status(state, label, detail)`, `emit_sources(message_id, sources)`,
  `ask_quick_replies(prompt, options, allow_free_text)` + `resolve_choice(...)`. `text`
  is emitted implicitly by streaming a model node.

Helpers you'll want: `build_chat_model(registry.resolve_provider(cfg))` and
`astream_message(model, messages) -> AIMessage` (`app/graphs/model.py`); for tools,
`mcp_call(ctx, client, tool_name, **args)` and `allowed_tool_names(cfg)`
(`app/mcp/client.py`), and `client_for(server, token)` (`app/mcp/transport.py`).

**Two shapes** (`docs/08` §Fragment shapes):

- **Fixed retrieve-then-generate** (recommended; `it_helpdesk.py` is the reference): the
  node calls tools by name, then streams the answer. The model is given **no tools**, so
  its scope is structurally zero — the graph calls exactly the allowlisted tools.
- **Tool-calling agent**: bind tools with `build_tools(cfg, ctx, client, specs)` and let
  the model choose. More flexible, harder to test.

Minimal no-tools fragment (a passthrough / echo-shaped bot):

```python
def build_my_fragment(cfg, registry, *, answer_model=None):
    model = answer_model or build_chat_model(registry.resolve_provider(cfg))

    def flow(b):
        async def answer(state, config):
            msg = await astream_message(model, [SystemMessage(cfg.prompt.system), *state["messages"]])
            return {"messages": [msg]}
        b.add_node("answer", answer)
        b.set_entry_after_guard("answer")
        b.add_edge("answer", END)

    return GraphFragment(flow)
```

Two gotchas that have already bitten us:

- **`emit_sources`'s `message_id` must be the answer `AIMessage.id`** (what `astream_message`
  returns) — the gateway maps it to the client bubble; any other value misattaches the
  citation (`docs/04` §3).
- **Any model call inside any node leaks into the client `text` stream** via
  `stream_mode="messages"`. An auxiliary/classification call must pass
  `config={"tags": [TAG_NOSTREAM]}` (see `make_guard_node` in `skeleton.py`).

## Step 4 — Register the fragment

In `gateway/app/graphs/registry.py`, add one line to `FRAGMENT_BUILDERS`:

```python
"my-bot": lambda cfg, registry: build_my_fragment(cfg, registry),
```

The key must equal the bot's `graph:` value, or boot fails on validation check 13.

## Step 5 — Validate

```bash
cd gateway && uv run python -m app.cli validate-config ../config/
```

Must pass (all 13 checks, `docs/03`) before the gateway will boot. Common trips: the
`graph` isn't registered (13), a tool's `mcp_server` isn't defined (2), a `*_env` secret
isn't set (3), or a public bot has `guard.enabled: false` (7 — a warning).

## Step 6 — Tests (land with the code)

Copy the pattern in `gateway/tests/test_it_helpdesk.py`: build the fragment with fake
seams (`GenericFakeChatModel`; an in-memory FastMCP server via
`mcp.shared.memory.create_connected_server_and_client_session`), run it through
`build_bot_graph` + `create_app`, and assert the SSE events with the `collect` helper.
Required per `docs/06`:

- **T7** conformance (operates only on `BotState`, reads identity from `ctx`, emits via
  helpers, reaches `END`).
- **T4** scoping if it has tools (only allowlisted tools reachable; deny wins).
- **T3** if `requires_auth`: identity isolation is MANDATORY — cannot ship without it.
  Also worth a T3.3 indirect-injection test (tool output is untrusted).

## Step 7 — Enable + go-live gates

- Public bot: guard enabled (Step 2) and the guard actually declines out-of-scope input
  (T4.2, live).
- **First public bot only:** the T10-E manual screen-reader audit + a published
  accessibility conformance statement (`docs/05` §11) — a human gate.
- Point config at the real endpoints and confirm end-to-end before flipping `enabled`.

## Auth bots (extra)

`requires_auth: true` requires an `identity:` block (`subject_claim`, `required_roles`)
and a global `auth:` block (check 5). The gateway validates the bearer token pre-stream,
builds the trusted `Identity`, and injects it into every MCP call via `_meta`. Your
fragment does nothing special — `mcp_call` carries it. The MCP server MUST enforce
own-data-only from that identity (T3, mandatory). The widget supplies the token via
`data-get-token`; `token_expired` triggers a refresh + retry automatically.

## Checklist

- [ ] (tools) `mcp_servers` entry + `bearer_token_env` in `.env`/CI
- [ ] `config/bots/<id>.yaml` (stem == id, `graph:` set, guard on if public)
- [ ] `app/graphs/<id>.py` fragment (reads ctx at runtime, right `emit_sources` id, TAG_NOSTREAM on aux model calls)
- [ ] one line in `FRAGMENT_BUILDERS`
- [ ] `validate-config` passes
- [ ] tests (T7; T4 if tools; T3 if auth)
- [ ] go-live gates (guard declines; T10-E for the first public bot)
