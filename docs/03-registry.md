# 03 — Bot Registry & Config Schema

Config is data, validated at startup, git-managed, PR-reviewed. No admin UI.
Secrets are referenced, not stored. Every risky default is safe.

## Layout

```
config/
  global.yaml
  bots/{id}.yaml
```

One file per bot; the `id` field inside is authoritative (lint: filename stem == id).
Loaded + validated + merged with global defaults at startup; held immutable in memory.
Optional SIGHUP hot-reload later (on validation failure, keep old config, log loudly).

## global.yaml

```yaml
version: 1

model_providers:
  default:
    base_url: "http://vllm:8000/v1"
    api_key_env: "VLLM_API_KEY"          # secret by ENV NAME
    default_model: "llama-3.3-70b-instruct"
    timeout_s: 60
    max_retries: 2
  fast-small:
    base_url: "http://vllm-small:8000/v1"
    api_key_env: "VLLM_SMALL_API_KEY"
    default_model: "llama-3.1-8b-instruct"
    timeout_s: 30

mcp_servers:
  course-catalog:
    transport: "streamable-http"          # stdio | streamable-http
    url: "http://course-catalog-mcp:9000/mcp"
    timeout_s: 20
  enrollment:
    transport: "streamable-http"
    url: "http://enrollment-mcp:9000/mcp"
    timeout_s: 20
  it-helpdesk:                              # externally-hosted MCP server, bearer-token auth
    transport: "streamable-http"
    url: "https://mcp-it-helpdesk.example.org/mcp"
    timeout_s: 20
    bearer_token_env: "IT_HELPDESK_MCP_TOKEN"  # secret by ENV NAME; authenticates the
                                                # GATEWAY to this server — orthogonal to
                                                # the per-call `_identity` injected into
                                                # every tool call (docs/04 §7): this is
                                                # "may we connect", not "whose data".

# Reverse-proxy trust. X-Forwarded-For is client-forgeable: it is honored (RIGHTMOST
# hop — the one appended by YOUR proxy) only when true. Default false (secure). Set
# true only when a trusted reverse proxy (the compose Caddy) fronts every request;
# otherwise anonymous rate limits key on the direct peer address.
network:
  trust_forwarded_for: true
  # DEV ONLY: dev_allow_localhost (default false) lets any http(s) localhost/127.0.0.1/
  # [::1] origin on ANY port embed every bot, bypassing embedding.allowed_origins. For
  # local development against changing dev-server ports; never enable in production.
  dev_allow_localhost: false

auth:
  issuer: "https://sso.uni.edu/realms/university"
  jwks_url: "https://sso.uni.edu/realms/university/protocol/openid-connect/certs"
  audience: "chatbots"
  leeway_s: 30

defaults:
  session_ttl_s: 7200   # 120 min; per-bot overridable
  max_message_chars: 4000
  history_max_turns: 20
  rate_limit:
    anonymous:     { requests_per_min: 15, requests_per_day: 300 }
    authenticated: { requests_per_min: 60 }
  guard: { enabled: false }
  greeting: { mode: "client_initiated" }

# Global-only keys (NOT per-bot overridable) live outside `defaults`.
streaming: { heartbeat_s: 15 }

# Deployment default theme (from the design mockup). External clients override same keys.
theme:
  dark_mode: "auto"              # auto (prefers-color-scheme) | light | dark
  light:
    "--bg": "#ffffff"
    "--surface": "#f4f4f5"
    "--surface-2": "#ececee"
    "--border": "#e2e2e5"
    "--text": "#18181b"
    "--text-muted": "#6b6b70"
    "--primary": "#a6093d"
    "--primary-hover": "#8a0732"
    "--accent": "#f2c879"        # decorative eyebrow glyph only (exempt from contrast)
    "--on-primary": "#ffffff"    # icon/text on primary surfaces (launcher, send)
  dark:
    "--bg": "#161618"
    "--surface": "#1e1e21"
    "--surface-2": "#27272b"
    "--border": "#34343a"
    "--text": "#f4f4f5"
    "--text-muted": "#9a9aa1"
    "--primary": "#c2355c"
    "--primary-hover": "#a6093d"
    "--accent": "#f2c879"
    "--on-primary": "#ffffff"
  radius:
    "--radius-panel": "22px"
    "--radius-card": "12px"
    "--radius-bubble": "14px"
    "--radius-input": "12px"
    "--radius-send": "14px"
```

## Config shape: unified defaults ↔ per-bot overrides

`defaults` and the per-bot **overridable subset** use the **identical nesting**, so
merge is one generic deep-merge (per-bot wins; rate-limit tiers merged independently).
Global-only keys (`streaming`, `auth`, `model_providers`, `mcp_servers`, and the
deployment `theme` defaults) live OUTSIDE `defaults` and cannot be overridden per bot.

Overridable per bot (must match `defaults` shape): `session_ttl_s`,
`max_message_chars`, `history_max_turns`, `rate_limit`, `guard`, `greeting`.
Everything else is global-only.

## Per-bot schema (annotated example)

```yaml
version: 1
id: "enrollment"
name: "Enrollment Assistant"
description: "Helps with enrollment questions and credit checks."
enabled: true

model:
  provider: "default"
  temperature: 0.2
  max_tokens: 1024

prompt:
  system: |
    You are the university enrollment assistant. …

# Which code-defined graph fragment this bot uses (docs/04 §9; never a graph
# DEFINITION as data, just its name). Default "echo". Checked at boot (check 13).
# Stock fragments ("passthrough", "tool-agent") make a bot CONFIG-ONLY — no fragment
# code, no registry edit (docs/09).
graph: "enrollment"

# Parameters for the selected fragment (check 14). Each fragment declares a Pydantic
# params model (extra="forbid"): unknown keys, wrong types, or out-of-range values
# fail boot. Params configure a FIXED shape — never topology (graph-as-YAML remains
# out of config, see §Deliberately OUT). Bespoke fragments take none.
# For `graph: "tool-agent"`:
#   max_tool_rounds: 1        # default 1 = pick tools once, then answer (tool output
#                             # can only influence answer TEXT). >1 re-enters the model
#                             # with tool output in context — explicit opt-in, max 5.
#   sources_from: ["tool_a"]  # whose results become the `sources` event; must be a
#                             # subset of the effective allowlist (allow − deny).
#   max_tool_result_chars: 4000  # per-result context budget (bounded prompt)
graph_params: {}

requires_auth: true
identity:
  subject_claim: "sub"
  required_roles: ["student"]

tools:
  mcp_servers: ["enrollment"]
  allow: ["enrollment.get_my_enrollment", "enrollment.get_my_credits"]
  deny:  ["enrollment.admin_override"]

# Overridable subset — same shape as global `defaults`:
guard:    { enabled: true, provider: "fast-small", on_out_of_scope: "decline" }
greeting: { mode: "client_initiated" }
session_ttl_s: 1800
max_message_chars: 2000
history_max_turns: 12
rate_limit:
  authenticated: { requests_per_min: 40 }

embedding:
  mode: "launcher"              # launcher | inline | standalone   (was: inline|overlay)
  allowed_origins: ["https://www.uni-osnabrueck.de"]

# Persistent suggestion chips shown in the empty/idle state (NOT protocol quick_replies).
# Click sends `query` as a normal message. Localized per lang.
starter_replies:
  de:
    - { label: "VPN einrichten",  query: "Wie richte ich den VPN ein?" }
    - { label: "eduroam / WLAN",  query: "Wie verbinde ich mich mit eduroam?" }
    - { label: "Passwort ändern", query: "Wie ändere ich mein Passwort?" }
    - { label: "Bibliothek",      query: "Fragen zur Bibliothek" }
  en:
    - { label: "Set up VPN",      query: "How do I set up the VPN?" }
    # …

# Optional per-bot theme token overrides (rare for internal bots; common for
# external-client bots). Partial token maps keyed by the same `--*` names as the
# deployment `theme`, per light/dark (+ optional radius/dark_mode); deep-merged over
# the deployment theme. Omitted = inherit deployment `theme`.
# theme:
#   light: { "--primary": "#7a0019", "--on-primary": "auto" }
#   dark:  { "--primary": "#d9718c" }

observability:
  log_message_content: false
  audit: { enabled: false }
```

### Orchestrator ("front door") bot

An orchestrator is a bot with a `routes` block. Its graph fragment composes the listed
bots' fragments as subgraphs (see `04-node-contract.md`).

`routes.mode` (check 12): `"menu"` (default — a click selects the lane) or
`"classifier"` (step 12 — the menu stays with free text allowed; a typed message is
classified onto a target by the router's own `model.provider`, menu as fallback).
In classifier mode each target may carry a `route_hint:` — the classifier's routing
description for that target (fallback: the target bot's `description`, then its
`label`). A `context.topic` exactly matching a target id routes deterministically
without a model call.

```yaml
version: 1
id: "assistant"
name: "University Assistant"
enabled: true

model:
  provider: "fast-small"            # only used for optional free-text routing fallback

prompt:
  system: "You route users to the right specialised assistant."

requires_auth: false                # PUBLIC front door

# Routing target set. Each must satisfy the auth-posture invariant (check 11).
routes:
  mode: "menu"                      # v1: menu only. "classifier" reserved for v2.
  sticky: true                     # stay in a sub-bot for follow-ups
  targets:
    - { bot: "course-catalog", label: "Courses" }
    - { bot: "faq",            label: "General questions" }
    - { bot: "library",        label: "Library" }
    # NOTE: "enrollment" (requires_auth:true) is NOT listed here — a public router
    # may not route to an auth bot (check 11). An authenticated internal front door
    # (requires_auth:true) may include it.

guard:    { enabled: false }        # the menu IS the scoping for a router
greeting: { mode: "bot_greeting" }  # opens with the menu

embedding:
  mode: "launcher"
  allowed_origins: ["https://www.uni.edu"]

rate_limit:
  anonymous: { requests_per_min: 15, requests_per_day: 300 }
```

### Minimal public bot
```yaml
version: 1
id: "faq"
name: "Campus FAQ"
enabled: true
model: { provider: "default" }
prompt: { system: "You answer general questions about campus facilities and hours." }
requires_auth: false
tools: { mcp_servers: [] }
guard: { enabled: true }
embedding:
  mode: "launcher"
  allowed_origins: ["https://www.uni.edu", "https://library.uni.edu"]
rate_limit:
  anonymous: { requests_per_min: 10, requests_per_day: 200 }
```

## The orthogonal-flags matrix (do not conflate)

| Flag | Controls | Default |
|---|---|---|
| `requires_auth` | Keycloak token validated + identity injected | false |
| `embedding.allowed_origins` | which sites may embed the widget | [] |
| `routes` (presence) | bot is an orchestrator | absent |

## Secrets boundary

Config holds references (`api_key_env`, `jwks_url`). Values from env/secret store.
OpenAI-surface API keys stored hashed in a secret store, never YAML. Loader resolves
`*_env` at startup; missing var → fail boot.

## Validation (Pydantic v2; fail boot on any failure)

**Startup checks:**
1. Every `model.provider` exists in `global.model_providers`.
2. Every `tools.mcp_servers` entry exists in `global.mcp_servers`.
3. Every `*_env` reference resolves.
4. All bot `id`s unique and match `^[a-z0-9][a-z0-9-]{1,62}$`.
5. `requires_auth` ⇒ `identity` present ⇒ global `auth` present.
6. `guard.enabled` ⇒ `guard.provider` resolves.
7. WARN (not fail) if a public no-auth, non-router bot has `guard.enabled:false`.
8. Overridable per-bot keys use the same shape as `defaults` (schema enforces).
9. Theme contrast — for BOTH `light` and `dark` resolved token sets:
   - `--primary` as TEXT on `--bg` ≥ 4.5:1  (links, starter chips, quick-reply chips).
   - `--text` on `--bg` ≥ 4.5:1; `--text-muted` on `--bg` and on `--surface` ≥ 4.5:1.
   - `--on-primary` on `--primary` ≥ 3:1  (icons on launcher/send are graphical, SC 1.4.11).
   - `--accent` is decorative (eyebrow glyph beside the bot-name label) → EXEMPT.
   FAIL boot on any violation. This is the guardrail that catches an external client
   shipping a pale `--primary` that makes links or the send icon illegible.
10. `routes.targets[].bot` each exists, is `enabled`, and is not the router itself
    (no self/cycle).
11. **Auth-posture invariant:** for a router, every target bot's `requires_auth` ≤ the
    router's `requires_auth`. (A public router cannot list an auth bot.)
12. `routes.mode` ∈ {`menu`} for v1 (`classifier` reserved, rejected in v1).
13. `graph` resolves to a fragment registered in the code-side graph registry (fails
    boot on a typo/unimplemented graph, rather than erroring on the bot's first request).
14. `graph_params` validates against the selected fragment's declared params model
    (extra="forbid": unknown keys/wrong types/out-of-range fail boot). Stock-fragment
    invariants hold: `sources_from` ⊆ effective allowlist (allow − deny);
    `tool-agent` requires a non-empty effective allowlist. Bespoke fragments accept
    no params — a stray `graph_params` block on them fails boot, never silently ignored.

Ship a `validate-config` CLI running all checks without booting. Wire into CI.

## Runtime access

```python
registry.get(bot_id)            -> BotCfg | raises unknown_bot
registry.resolve_provider(cfg)  -> ModelProvider (secret injected)
registry.mcp_for(cfg)           -> [McpServerCfg] (allowlist applied)
registry.graph_for(bot_id)      -> compiled graph (cached; composes subgraphs if router)
registry.resolve_theme(cfg)     -> ResolvedTheme (deployment theme + per-bot override,
                                    `--on-primary` resolved black/white by luminance
                                    when set to "auto")
```

Nothing downstream reads YAML — only typed config objects.

## Deliberately OUT of config (v1)

- No theming DSL. Theme is a FIXED token set with deployment defaults + overrides —
  never arbitrary CSS injection.
- No flow/graph definitions as data — graphs live in code; config only references
  which graph a bot uses (and, for routers, which bots to compose).
- No tenant/ownership fields — single-tenant per deployment.
- No `openai_api` block — the OpenAI surface was cut.
- No `form` config — quick-replies only.
- No prompt A/B/versioning machinery (git history is versioning).

Keep the schema boring.
