# Scoped AI Support Bots

A self-hosted, multi-bot chatbot ecosystem for a university: several **narrowly-scoped**
support bots (IT helpdesk, course catalog, enrollment, …), each backed by an
OpenAI-compatible model, each calling internal systems as **MCP tools**, embeddable on
any site through one hand-built accessible widget.

Three independent pieces:

- **Widget** (`widget/`) — vanilla-TS, Shadow-DOM, single `widget.js`. Renders the chat
  UI, consumes the SSE protocol. WCAG 2.1 AA built in.
- **Gateway** (`gateway/`) — FastAPI. Bot registry + config, LangGraph runner, auth,
  MCP tool calling, streaming SSE. One process serves every bot.
- **MCP servers** — one per backend system, run elsewhere; the gateway calls them over
  streamable-HTTP and enforces identity server-side.

```
Embedded widget ──POST /api/v1/bots/{id}/chat (SSE)──► Gateway ──► OpenAI-compatible model
                                                          │  └──► MCP servers (tools)
                                                          └──► Keycloak (auth, if required)
```

**Single-tenant by design:** one deployment = one tenant (university or external client).
More clients = more independent deployments, not tenant-scoping in the code.

## Why a custom protocol (not "just an OpenAI API")

The widget talks to a **server-side orchestrator**, not a model. The orchestrator pauses
for quick-reply choices, emits citations and progress, owns the session, and enforces
auth + tool scoping — none of which the OpenAI chat-completions API expresses. We *do*
speak OpenAI-compatible on the gateway→model hop. See `docs/01-protocol.md` and the
`docs/02-dual-api.md` tombstone for the full rationale.

## Repository layout

```
gateway/        FastAPI app (registry, runtime, graphs, auth, mcp) + tests
widget/         TS widget source, build to dist/widget.js + tests
config/         global.yaml + bots/*.yaml  (git-managed, PR-reviewed, no secrets)
docs/           the contracts — read these before changing behavior
caddy/          reverse-proxy config (TLS, SSE, static widget)
design/         wolke visual/interaction reference
docker-compose.yml   gateway + widget + caddy
```

## Documentation (the contracts)

Read the one you need; they are the source of truth and override code.

| Doc | What |
|---|---|
| `docs/00-overview.md` | Architecture, tenancy, key decisions. Start here. |
| `docs/01-protocol.md` | Widget ↔ gateway wire protocol (SSE events). |
| `docs/03-registry.md` | Bot/global config schema + the 13 validation checks. |
| `docs/04-node-contract.md` | The LangGraph interface every bot satisfies. |
| `docs/05-accessibility.md` | Widget WCAG 2.1 AA spec. |
| `docs/06-integration-and-tests.md` | End-to-end sequences + test plan (T1–T11). |
| `docs/07-deployment.md` | Deploy topology, widget delivery, external-service config. |
| `docs/08-integration-scenarios.md` | Which backends fit + the overhead of each. |
| `docs/09-adding-a-bot.md` | **How to add a bot** (step by step). |
| `docs/BUILD_PLAN.md` | Sequenced build steps + current status. |

## Quickstart (local dev)

**Gateway** (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
cd gateway
uv venv --python 3.12 && uv pip install -e ".[dev]"
# secrets are referenced by env NAME in config; any value works for local validate/test:
export VLLM_API_KEY=x VLLM_SMALL_API_KEY=x UOS_DOCS_MCP_TOKEN=x
uv run python -m app.cli validate-config ../config/   # must pass before boot
uv run pytest -q                                       # tests
uv run mypy --strict app                               # types
uv run uvicorn app.main:app --reload                   # serve on :8000
```

**Widget** (Node, Vite):

```bash
cd widget
npm install && npx playwright install chromium
npm run dev            # dev host with a stubbed backend: /?mode=launcher|inline
npm test               # Vitest units
npm run test:a11y      # Playwright + axe (WCAG)
npm run build          # → dist/widget.js
```

**Full stack** (needs external vLLM / MCP / Keycloak reachable):

```bash
cp .env.example .env    # fill in secrets + SITE_ADDRESS
# edit config/global.yaml: base_url / mcp_servers.url / auth.jwks_url → your services
docker compose up --build
```

## Embedding the widget

Deploy `widget.js` once; every site references it by URL and adds its origin to the
bot's `embedding.allowed_origins`:

```html
<script src="https://assistant.uni-osnabrueck.de/widget.js"
        data-bot-id="it-helpdesk"></script>
```

Attributes: `data-bot-id` (required), `data-base-url` (if the gateway is a different
origin), `data-mode` (`launcher`|`inline`|`standalone`), `data-scheme` (`light`|`dark`),
`data-get-token` (name of a global returning a bearer token, for auth bots). See
`docs/07-deployment.md`.

## Status

Skeleton complete and exercised by a reference bot; see `docs/BUILD_PLAN.md` for the
authoritative, per-step status. In short: gateway + widget + auth + abuse controls + MCP
transport are done and tested; the `it-helpdesk` reference bot demonstrates the full
tool-using path. Remaining work is per-bot config/fragments and going live against real
endpoints (which needs the external model + MCP servers).

## Conventions

- `mypy --strict` on the gateway, `tsc --strict` on the widget. Tests land with code.
- Config holds secret **references** (`*_env`), never values. `.env` is git-ignored.
- The contracts in `docs/` are fixed — if code wants to bend one, raise it, don't drift.

See `CLAUDE.md` for the full operating rules (golden rules, tech stack, build order).
