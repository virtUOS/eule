# CLAUDE.md — Agent operating instructions

You are building **Scoped AI Support Bots**: a self-hosted, multi-bot chatbot
ecosystem for a university. Read `docs/00-overview.md` first, then the spec
referenced by whatever you're working on.

## Golden rules (do not violate)

1. **Contracts are fixed.** The wire protocol (`docs/01-protocol.md`), config
   schema (`docs/03-registry.md`), and graph interface (`docs/04-node-contract.md`)
   are contracts. Do not change them to make code easier — raise it as a question.
2. **Identity never flows through the model.** Authenticated `subject`/claims are
   injected into tool calls out-of-band via `RuntimeContext`. They are NEVER in
   `BotState`, NEVER a model-visible tool parameter, NEVER in the prompt. See
   `docs/04-node-contract.md` §7. This is a security requirement, not a preference.
3. **Scope is enforced structurally, not by prompt.** Tool allowlists, graph
   topology, and MCP-side authorization are the real enforcement. Prompt text is
   defense-in-depth only.
4. **Fail fast on config.** Invalid bot config must fail `validate-config` and
   block boot. Never boot a bot with an invalid scope.
5. **Accessibility is built in, not audited on.** The widget follows
   `docs/05-accessibility.md` from the first commit.
6. **Secrets are referenced, never stored.** Config holds `*_env` references;
   values come from environment. No secrets in git.
7. **Single-tenant by design.** One deployment = one tenant (one university, or one
   external client). Never add tenant-scoping to the registry, sessions, or config.
   External clients get their own deployment. See `docs/00-overview.md` §Tenancy.
8. **Routing is bot logic, never gateway logic.** An orchestrator ("front door") is
   just a bot whose graph routes to other bots via subgraph composition. The gateway
   stays dumb: it runs `bot_id`'s graph and knows nothing bot-specific.

## Tech stack

- **Gateway:** Python 3.12, FastAPI (async), SSE via `StreamingResponse`.
- **Orchestration:** LangGraph. One compiled graph per bot, cached.
- **Tools:** MCP servers (official Python SDK), streamable-HTTP transport.
- **Config:** Pydantic v2 models, loaded from YAML.
- **Auth:** Keycloak OIDC; validate JWT against JWKS.
- **Model:** OpenAI-compatible endpoint (self-hosted vLLM/LiteLLM). Use an
  OpenAI-compatible client; base_url from config.
- **Widget:** Vanilla TypeScript, no framework. Shadow DOM. Built to a single
  `widget.js`. SSE consumed via `fetch` + `ReadableStream` (NOT `EventSource`).
- **Deployment:** Docker Compose.

## Repo layout

```
gateway/            # FastAPI app, registry, graph runner, adapters
  app/
    api/            # native + openai routers
    registry/       # config models + loader + validation
    runtime/        # RuntimeContext, graph runner, event translation
    graphs/         # shared skeleton + per-bot graph fragments
    auth/           # keycloak jwt validation
    mcp/            # mcp client wrapper (identity injection)
  tests/
config/
  global.yaml
  bots/*.yaml
widget/             # TS source, build to dist/widget.js
  src/
  tests/
mcp-servers/        # one dir per backend system
docs/
```

## Commands

- Install (gateway): `uv sync` (or `pip install -e gateway`)
- Run gateway: `uvicorn app.main:app --reload` (from `gateway/`)
- Validate config: `python -m app.cli validate-config config/`
- Test gateway: `pytest gateway/tests`
- Conformance harness: `pytest gateway/tests/conformance` (see docs/06 §T7)
- Widget dev: `npm run dev` (from `widget/`)
- Widget build: `npm run build`
- Widget test: `npm test` (Vitest) + `npm run test:a11y` (Playwright + axe)
- Full stack: `docker compose up`

## Conventions

- Type everything. `mypy --strict` on gateway; `tsc --strict` on widget.
- Every new bot = config file + graph fragment + (optional) MCP server. An
  orchestrator is a bot whose fragment composes other bots' fragments as subgraphs.
  If a bot needs the gateway changed, the abstraction is wrong — stop and ask.
- Tests land with the code, not after. Security tests (docs/06 §T3) are mandatory.
- Small, focused commits mapped to `docs/BUILD_PLAN.md` steps.

## Build order

Follow `docs/BUILD_PLAN.md` strictly. Do not build bots before the skeleton, or
auth after the first auth bot.

## Explicit non-goals

No conversation persistence, no self-serve bot builder, no public identity-aware bots,
no graph-as-YAML, **no OpenAI-compatible surface, no forms (quick-replies only), no
multi-tenancy.** See `docs/00-overview.md` §6.

## Design reference

The widget has an existing design mockup + standalone demo at `design/`
(see its README.md). Treat it as the **visual and interaction source of truth** for the
widget: layout, styling, copy, quick-reply/form appearance, open/close behavior.

Rules for using it:
- Port its **look and interaction**, not necessarily its code structure.
- Where the mockup conflicts with a contract, the **contract wins** and you raise it:
  - Accessibility (`docs/05-accessibility.md`) — the mockup may not implement the
    two live-region strategy, focus rules, or contrast-validated theming. These are
    non-negotiable; add them even if the mockup omits them.
  - Wire protocol (`docs/01-protocol.md`) — the mockup likely uses mock/stub data;
    real rendering is driven by protocol events.
  - Shadow DOM isolation and `embedding.mode` (inline/overlay) may not be in the mockup.
- The standalone demo is a useful harness for build-step 2 — you may adapt it into
  the standalone page (`docs/05-accessibility.md` §9) rather than starting from scratch.
S