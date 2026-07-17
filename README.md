# eule: orchestration bot

**Orchestration backend and embeddable widget for scoped university support chatbots.** You define each bot in a YAML file — its system prompt, its
model, and the internal systems it may call as tools — and the gateway serves all of them
from a single process. A university might run an IT-helpdesk bot, a study-advice bot, and
a front-door bot that routes between them, each answering only within its lane, each
embeddable on any web page with a two-line `<script>` tag.

The design goal is **safe, boring operations**: adding or changing a bot is a
reviewed config change, not a code deploy; a bot can only reach the tools its config
allows; and the authenticated user's identity is enforced server-side, never passed
through the model. Accessibility (WCAG 2.1 AA) is built into the widget from the first
line, not bolted on.

> **Status:** the platform (gateway, widget, auth, rate-limiting, MCP tool-calling,
> stock bot fragments, the router front door) is built and tested. Going fully live
> needs your external model + MCP endpoints wired in. See `docs/BUILD_PLAN.md` for
> authoritative per-step status.

---

## How it fits together

Three independent pieces, plus the external services you provide:

```
                          ┌──────────────────────────────────────────┐
  Embedded widget         │                Gateway                    │
  (widget.js on any  ──POST /api/v1/bots/{id}/chat (SSE)──►  registry │
   site, Shadow DOM)      │  session · rate-limit · origin gate       │
                          │  LangGraph runner ── per-bot graph        │
                          └───┬───────────────┬──────────────┬────────┘
                              │               │              │
                    OpenAI-compatible    MCP servers     Keycloak
                    model (vLLM/         (your tools,    (OIDC, only
                    LiteLLM/…)           streamable-HTTP) for auth bots)
```

- **Widget** (`widget/`) — vanilla TypeScript, Shadow-DOM isolated, built to a single
  `widget.js`. Renders the chat UI and consumes the gateway's SSE event protocol.
- **Gateway** (`gateway/`) — FastAPI. Loads the bot registry from config, runs one
  LangGraph graph per bot, validates auth, calls MCP tools with identity injected
  out-of-band, and streams responses as Server-Sent Events. One process serves every bot.
- **MCP servers** — one per backend system (docs search, a database, a REST API…). They
  run wherever you like; the gateway calls them over streamable-HTTP and they enforce
  "this user, their data only".

**Single-tenant by design.** One deployment serves one tenant (one university, or one
external client). More clients means more independent deployments — there is no
tenant-scoping in the registry, sessions, or config.

**Why a custom widget↔gateway protocol instead of a plain OpenAI API?** The widget talks
to a *server-side orchestrator*, not a model: it pauses for quick-reply menus, streams
progress and citations, owns the session, and enforces auth + tool scope — none of which
the OpenAI chat-completions shape can express. (The gateway→model hop *is*
OpenAI-compatible.) Full rationale in `docs/01-protocol.md`.

---

## Deployment

The repository ships a Docker Compose stack — **gateway + widget (static `widget.js`) +
Caddy** (TLS + reverse proxy + SSE-safe buffering). The model, MCP servers, and Keycloak
are **external** services you point the config at; they are not part of the compose stack.

### 1. Provide the external services

| Service | Needed for | Config field |
|---|---|---|
| OpenAI-compatible model endpoint (vLLM, LiteLLM, or a hosted bot) | every bot that calls a model | `model_providers.<name>.base_url` |
| MCP server(s) | any bot with tools | `mcp_servers.<name>.url` |
| Keycloak (OIDC) | only bots with `requires_auth: true` | `auth.issuer` / `auth.jwks_url` |

### 2. Configure and bring it up

```bash
cp .env.example .env
# .env: fill in the secret VALUES (API keys, MCP tokens) + SITE_ADDRESS (your hostname).
# config/global.yaml: point base_url / mcp_servers.url / auth.jwks_url at your services.

docker compose up --build
```

Caddy waits for the gateway's healthcheck before serving, so there are no boot-time 502s.
The gateway **fails fast**: if the config is invalid it refuses to boot rather than
starting a misconfigured bot (see *Configuration → Validation*).

### 3. Deployment notes

- **Reverse proxy & rate limiting.** The stack sets `network.trust_forwarded_for: true`
  in `config/global.yaml` because Caddy fronts the gateway — the client IP used for
  anonymous rate limits is read from the rightmost `X-Forwarded-For` hop. **If you expose
  the gateway directly (no trusted proxy), set this to `false`**, or a forged header
  bypasses rate limits.
- **Secrets never live in config.** `config/*.yaml` holds only environment-variable
  *names* (the `*_env` fields); the values come from `.env` (git-ignored). Nothing secret
  is committed.
- **Sessions are in-memory** (single instance). Survive-reload persistence works via the
  widget's `localStorage`; horizontal scaling (a Redis checkpointer) is a documented
  swap-point, not yet built (`docs/BUILD_PLAN.md` → *Later / v2*).
- **Health:** `GET /healthz` on the gateway.

Full topology, hosting options, and widget delivery: `docs/07-deployment.md`.

---

## Configuration

**Everything about a bot lives in YAML.** Global settings in `config/global.yaml`; one
file per bot in `config/bots/<id>.yaml` (the filename stem must equal the bot `id`).
Config is git-managed and PR-reviewed — treat it as the deployment's source of truth.

### Global — `config/global.yaml`

```yaml
model_providers:              # OpenAI-compatible endpoints, referenced by name
  default:
    base_url: "http://vllm:8000/v1"
    api_key_env: "VLLM_API_KEY"        # secret by ENV NAME, never a value
    default_model: "llama-3.3-70b-instruct"
  fast-small:                          # a cheaper model for guards / simple bots
    base_url: "http://vllm-small:8000/v1"
    api_key_env: "VLLM_SMALL_API_KEY"
    default_model: "llama-3.1-8b-instruct"

mcp_servers:                 # your tool backends (streamable-HTTP)
  uos-docs:
    url: "https://mcp-docs.example.org/mcp"
    bearer_token_env: "UOS_DOCS_MCP_TOKEN"   # authenticates the gateway to the server

auth:                        # Keycloak OIDC — required once any bot sets requires_auth
  issuer: "https://sso.example.org/realms/university"
  jwks_url: "https://sso.example.org/realms/university/protocol/openid-connect/certs"
  audience: "chatbots"

network:
  trust_forwarded_for: true  # true only behind a trusted proxy (see Deployment)

defaults: { session_ttl_s: 7200, max_message_chars: 4000, history_max_turns: 20, … }
theme: { … }                 # light/dark design tokens, contrast-validated at boot
```

### A bot — `config/bots/<id>.yaml`

Most bots need **no code at all** — they select a *stock graph fragment* and parameterize
it. Example, a config-only tool-using bot:

```yaml
version: 1
id: "campus-search"
name: "Campus Search"
description: "Finds information on the university website."   # also used by the guard
enabled: true

graph: "tool-agent"          # a stock fragment (see table below)
graph_params:
  max_tool_rounds: 1         # 1 = look up once, then answer (bounded)
  sources_from: ["uos_search"]   # which tool's results become citations

model:   { provider: "fast-small" }
prompt:  { system: "You help students find information. Answer only from tool results." }

requires_auth: false
tools:   { mcp_servers: ["uos-docs"], allow: ["uos_search"], deny: [] }
guard:   { enabled: true, provider: "fast-small" }   # decline off-topic (public bots)

embedding:
  mode: "launcher"
  allowed_origins: ["https://www.example.org"]       # sites permitted to embed this bot

starter_replies:
  en: [ { label: "Library hours", query: "What are the library's opening hours?" } ]
```

### Stock fragments — pick one with `graph:`

| `graph:` | What it does | Typical bot |
|---|---|---|
| `passthrough` | Streams the model with the conversation; no tools. | A prompted assistant, or a whole bot behind an OpenAI-compatible endpoint. |
| `tool-agent` | Bounded model-driven tool loop over the allowlisted MCP tools, then a final answer. | Retrieval / lookup bots. |
| `router` | The **front door**: routes to sub-bots, sticky, with an "other topic" escape. Two modes — `menu` (a click selects the lane) or `classifier` (menu stays, but a typed message is auto-routed by a cheap model, menu as fallback). | The "ask us anything" launcher. |

A **front door** is itself just a config-only bot:

```yaml
id: "assistant"
graph: "router"
routes:
  mode: "classifier"      # or "menu" (default): click-only, no model needed
  targets:
    #                       route_hint = the classifier's routing description per
    #                       target (fallback: the target bot's `description`)
    - { bot: "it-helpdesk",   label: "IT help",
        route_hint: "Technical problems: VPN, WiFi, passwords, university email" }
    - { bot: "campus-search", label: "Campus search",
        route_hint: "General campus info: opening hours, cafeteria, buildings" }
model: { provider: "fast-small" }      # classifier mode only: the ROUTER's own
                                       # provider does the classifying (a cheap/small
                                       # model from global model_providers is plenty)
greeting: { mode: "bot_greeting" }     # the menu is the greeting
```

In classifier mode a typed message is auto-routed (a click still works, and anything
the classifier isn't sure about falls back to the menu — the typed question is kept, so
no retyping after the click). A `context.topic` matching a target id routes
deterministically without any model call.

Bots with genuinely novel flows (custom interrupts, bespoke retrieval) can instead ship a
small hand-written fragment in `gateway/app/graphs/` — but that is the exception, not the
default. The full field reference is `docs/03-registry.md`; the step-by-step guide is
`docs/09-adding-a-bot.md`.

### Validation (fail-fast)

Before the gateway boots — and in CI — run:

```bash
cd gateway && uv run python -m app.cli validate-config ../config/
```

Fourteen checks must pass: every model provider and MCP server referenced exists, every
`*_env` secret is set, `graph_params` match the selected fragment, `sources_from` stay
within the tool allowlist, theme contrast meets WCAG, a public router only routes to
public targets, and more. **Invalid config blocks boot** — you never get a
half-configured bot in production.

### Adding or changing a bot

1. Edit or add a `config/bots/<id>.yaml` (and any new `mcp_servers` entry + its `.env`
   token).
2. `validate-config` (CI gate).
3. Restart the gateway. Config is volume-mounted, so **no image rebuild** for a
   config-only bot.

---

## Embedding the widget

Deploy `widget.js` once; each site references it and is listed in the bot's
`embedding.allowed_origins`:

```html
<script src="https://assistant.example.org/widget.js"
        data-bot-id="it-helpdesk"></script>
```

| Attribute | Purpose |
|---|---|
| `data-bot-id` | **required** — which bot to open |
| `data-base-url` | gateway origin, if different from the script's origin |
| `data-mode` | `launcher` (default) · `inline` · `standalone`; unknown values fall back to `launcher` |
| `data-mount` | CSS selector of the element to render into (inline/standalone) |
| `data-lang` | UI language, `de` / `en` (default: the page's `<html lang>`, by prefix) |
| `data-scheme` | force `light` / `dark` (default: follow the OS) |
| `data-get-token` | name of a global function returning a bearer token (auth bots) |
| `data-context-page` | page attribution sent with every turn; `"auto"` sends the page's origin + path (query string and fragment are **stripped** — they can carry tokens) |
| `data-context-topic` | topic hint sent with every turn (see routing below) |
| `data-context-locale` | locale hint for backends with a language field (e.g. askUOS) |

**How the context values route.** The three `data-context-*` values travel as the
protocol's `context` object on every turn — validated by the gateway against a strict
key allowlist and size caps, treated as untrusted data, and never able to carry
identity. What each one does:

- `topic` — steers the **front door**: on a `classifier`-mode router, a topic exactly
  matching a target bot id routes there deterministically (no model call). So an
  IT-pages embed can pre-steer `data-context-topic="it-helpdesk"` while the homepage
  embed lets the classifier/menu decide.
- `page` — recorded in the per-turn structured log (`eule.turn`) for usage
  attribution ("which page do questions come from"), never in metrics labels.
- `locale` — forwarded to Scenario-3 backends whose API takes a language field
  (`passthrough`'s `locale_body_field`); the widget UI language itself comes from
  `data-lang`.

**URL query parameters:** the production `widget.js` reads **none** — all
configuration is via the `data-*` attributes above (or the programmatic
`WolkeWidget.mount(options)` API). Only the *dev demo page* (`npm run dev`) accepts
`?mode=…&botId=…&lang=…&theme=…&topic=…&page=…` for manual testing; the shipped
`/standalone.html` is statically configured.

Pages served from the deployment's own host don't need to allowlist themselves. For
local development, set `network.dev_allow_localhost: true` in `config/global.yaml` to
accept any `localhost` / `127.0.0.1` origin on any port without listing each — it is
**off by default so production stays strict**. Details: `docs/07-deployment.md`.

---

## Local development

**Gateway** (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
cd gateway
uv venv --python 3.12 && uv pip install -e ".[dev]"
export VLLM_API_KEY=x VLLM_SMALL_API_KEY=x ASKUOS_API_KEY=x UOS_DOCS_MCP_TOKEN=x
uv run python -m app.cli validate-config ../config/   # config gate
uv run pytest -q                                       # tests
uv run mypy --strict app                               # types
uv run uvicorn app.main:app --reload                   # serve on :8000
```

**Widget** (Node, Vite):

```bash
cd widget
npm install && npx playwright install chromium
npm run dev            # dev host + stubbed backend: open /?mode=launcher
npm test               # Vitest units
npm run test:a11y      # Playwright + axe (WCAG) + behavior specs
npm run build          # → dist/widget.js
```

Conventions: `mypy --strict` (gateway) and `tsc --strict` (widget); tests land with the
code; the contracts in `docs/` are fixed — raise a question rather than drifting. See
`CLAUDE.md` for the full operating rules.

---

## Repository layout

```
gateway/   FastAPI app — registry, runtime, graphs (stock + bespoke fragments), auth, mcp
widget/    TypeScript widget source → dist/widget.js, plus unit + e2e/a11y tests
config/    global.yaml + bots/*.yaml   (git-managed, PR-reviewed, no secrets)
caddy/     reverse-proxy config (TLS, SSE, static widget)
docs/      the contracts — read before changing behavior
docker-compose.yml   gateway + widget + caddy
```

Bundled reference bots in `config/bots/`: `echo` (stub), `it-helpdesk` (bespoke
retrieve-then-generate), `campus-search` (stock `tool-agent`), `askuos` (stock
`passthrough` over an external OpenAI-compatible bot), `assistant` (stock `router` front
door).

## Documentation

The `docs/` files are the source of truth and override the code.

| Doc | What |
|---|---|
| `docs/00-overview.md` | Architecture, tenancy, key decisions. **Start here.** |
| `docs/01-protocol.md` | Widget ↔ gateway wire protocol (SSE events). |
| `docs/03-registry.md` | Bot/global config schema + the 14 validation checks. |
| `docs/04-node-contract.md` | The LangGraph interface every bot satisfies. |
| `docs/05-accessibility.md` | Widget WCAG 2.1 AA specification. |
| `docs/06-integration-and-tests.md` | End-to-end sequences + test plan. |
| `docs/07-deployment.md` | Deploy topology, widget delivery, external-service config. |
| `docs/08-integration-scenarios.md` | Which kinds of backend fit, and the overhead of each. |
| `docs/09-adding-a-bot.md` | **How to add a bot**, step by step. |
| `docs/BUILD_PLAN.md` | Sequenced build steps + current status. |

## License

MIT — see [LICENSE](LICENSE).
