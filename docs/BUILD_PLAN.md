# BUILD_PLAN.md — Sequenced implementation

Build the generic gateway + widget skeleton first, then plug in bots. Do not reorder.
Each step lists deliverables and the tests that gate it.

## Status (as of 2026-07-02)

Legend: ✅ done · 🟡 in progress · ⬜ not started

- ✅ **Step 0** — repo + tooling (see per-item notes; Docker Compose + a CI workflow file still outstanding)
- ✅ **Step 1** — gateway skeleton (gate green: T1, T8.1–2)
- ✅ **Step 2** — widget skeleton (gate green: T10-A, T10-B)
- ✅ **Step 3** — auth path (gate green: T2)
- 🟡 **Step 4** — 4a (abuse/embedding, T9.1/2/4) ✅ · 4b (MCP identity wrapper + tool scoping, T4.1/4.3, T3.2) ✅ · 4c (real MCP server + bot, guard classifier T4.2, live T4/T9.3, T10-E) ⬜ **infra-gated** (needs a model endpoint + a backend API to wrap)
- ⬜ **Step 5** · ⬜ **Step 5b** · ⬜ **Step 6**

Verified across the done steps: gateway `pytest` + `mypy --strict` + `validate-config`;
widget Vitest + Playwright(axe) + `tsc --strict`. Work is committed on `main`.

## Step 0 — Repo & tooling  ✅ (Docker Compose + CI workflow file: ⬜)
- ✅ Repo layout per `CLAUDE.md`. `uv` for gateway (py3.12), npm+Vitest+Playwright for widget.
- 🟡 CI checks all run locally and pass (`mypy --strict`, `tsc --strict`, `pytest`,
  `npm test`, `validate-config`, axe via Playwright) — a CI **workflow file** (e.g.
  `.github/workflows`) is not yet committed.
- ⬜ Docker Compose skeleton (gateway + one placeholder MCP + reference to vLLM/Keycloak).

## Step 1 — Gateway skeleton  ✅
- Config models (Pydantic) + loader + `validate-config` CLI with checks 1–12
  (`docs/03-registry.md`). Fail boot on invalid.
- Bot registry (in-memory, typed access API).
- In-memory session store / LangGraph MemorySaver checkpointer, TTL eviction. Wire
  checkpointer ONLY in the graph factory.
- RuntimeContext builder (auth stub for now).
- Graph factory + shared skeleton (guard/decline scaffolding).
- Config models + loader + `validate-config` CLI with checks 1–12
  (`docs/03-registry.md`), unified defaults↔override deep-merge, resolved-theme +
  contrast check. Fail boot on invalid.
- Native `/api/v1/bots/{id}/chat` endpoint: normalize input → run graph → translate
  event stream → SSE. Full event vocabulary (`docs/01-protocol.md`), incl. heartbeat.

- `GET /bots/{id}/config` bootstrap endpoint (theme + starter_replies
  + name + greeting mode), CORS-checked, ETag-cacheable. + resolve_theme (light/dark).

- **Gate:** T1 (protocol conformance), T8.1–2 (session/TTL).

## Step 2 — Widget skeleton  ✅
- Base the visual implementation on the mockup at `design/` (see its
  README), reconciled against `docs/05-accessibility.md` §14 and the protocol event
  model. Adapt its standalone demo into the standalone page rather than rebuilding.
- Shadow DOM mount; `<script>` bootstrap reading `data-*` attrs; `data-bot-id`,
  `getToken()` API, `embedding.mode`.
- SSE client via `fetch` + `ReadableStream` (NOT EventSource); parse all event types.
- Render text bubbles (streamed), quick-reply chips, and the sources footer. (No
  forms in v1.)
- Token-based theming: consume resolved theme tokens as CSS custom properties inside
  the Shadow root; deployment design-system values are the default. Dark mode via
  `prefers-color-scheme` is allowed as appearance.
- Base visuals on `design/widget-mockup/` reconciled against `docs/05` §14 and the
  protocol. Adopt its token approach; drop its localStorage persistence, its
  `/api/wolke/message` contract, always-visible free-text quick-replies, single
  live-region, and always-trap behavior (contracts win — see §14).
- **Accessibility built in from this commit** (`docs/05-accessibility.md` §§2–8):
  two live-region announcers, semantic controls, keyboard, focus rules, reduced-motion.
- Failure/timeout UX: keep partial text on error, retry affordance per `recoverable`.
- Standalone page (§9) + routing `/bots/{id}`.
- render the three form factors (launcher/inline/standalone). Consume
  bootstrap config; apply theme tokens as CSS vars in the Shadow root; support dark
  via dark_mode (auto = prefers-color-scheme). Render starter chips (send `message`)
  distinct from interrupt quick_replies (send `choice`). Reproduce the wolke visual
  (editorial bot messages, citation cards, launcher, typing indicator) from
  design/widget-mockup, but drop localStorage transcript, `/api/wolke/message`,
  `/api/branding` fetch, always-visible free-text quick-replies, single live-region.
- **Gate:** T10-A + T10-B in CI.

## Step 3 — Auth path  ✅
- Keycloak JWT validation (JWKS, issuer, audience, leeway).
- Bearer-token forwarding from widget via `getToken()` (Authorization header).
- Claims → Identity → RuntimeContext (never into BotState/prompt).
- token_expired handling end-to-end (host refresh).
- **Gate:** T2 (auth path).

## Step 4 — First MCP server + first real bot (template)  🟡
Split into slices; 4a + 4b are done, 4c is infra-gated (needs a model endpoint + a
backend API to wrap).

**4a — embedding & abuse controls  ✅**
- ✅ CORS allowlist + Origin gate on `/chat` (`forbidden_origin`) + OPTIONS preflight.
- ✅ Rate limiting for public/auth bots (per (bot, client); 429 + `retry_after`).
- ⬜ Per-session token/cost cap — deferred with the model (needs token accounting).

**4b — MCP identity wrapper + structural scoping  ✅**
- ✅ MCP client wrapper with out-of-band identity injection (`docs/04` §7); model-visible
  tool signatures carry no identity param. (streamable-HTTP transport lands in 4c.)
- ✅ Tool allow/deny resolution (denylist wins); only allowlisted tools are bound.

**4c — the real bot  ⬜ (infra-gated)**
- Simplest bot (course catalog, read-only, likely no auth): config + graph fragment
  (free-text + tools) + course-catalog MCP server (thin wrapper over the real API,
  enforces authz), streamable-HTTP transport.
- Guard node enabled for the public bot (cheap LLM classifier).

- **Gate:** T4 (scoping) — T4.1/4.3 ✅, T4.2 (guard declines) ⬜ needs classifier;
  T3.2 ✅. T9 (embedding/abuse) — T9.1/2/4 ✅, T9.3 ⬜. T10-E manual SR audit + publish
  conformance statement before this bot goes public ⬜.

## Step 5 — Second bot (auth + predefined-choice flow) — the real generalization test  ⬜
- enrollment bot: requires_auth + interrupt (quick-replies).
- enrollment MCP server enforcing own-data-only.
- Exercises everything the first bot didn't.
- **Gate (definition of "skeleton generalizes"):**
  - Path A end-to-end (`docs/06` §Path A).
  - T3 (identity isolation) — MANDATORY.
  - T5 (interrupt lifecycle).
  - **T7 conformance harness** green for both bots × {auth,unauth}. (The OpenAI
    surface was cut — there is one surface; no `{native,openai}` dimension.)

## Step 5b — Orchestrator (front door)  ⬜
- Compose the first two sub-bots (course-catalog + faq) into an `assistant` router
  fragment (subgraph composition, menu-first, sticky). Public router → public targets
  only (check 11).
- Gate: T11 (routing) + Path C end-to-end. Confirm sub-bot scoping is unchanged when
  reached via the router (T11.6).

## Step 6 — Remaining bots  ⬜
- Each = config + graph fragment + (reuse or new) MCP server. Fast, repetitive.
- Each must pass T7 harness + relevant T3/T4 before enable.

## Later / v2 (do not build now)
- Free-text classifier routing fallback (`routes.mode: classifier`) with a cheap model
  + "finding the right assistant…" status. Menu-first ships in v1.
- Dynamic mid-conversation re-routing (topic switch detection).
- Forms: additive `form` event + widget + a11y, when a concrete bot needs structured
  multi-field input.
- Redis checkpointer for horizontal scaling (one-line swap in the graph factory).
- Optional per-bot audit logging; observability (structured per-turn logs, metrics).
- (Only if a real consumer appears) an OpenAI-compatible translator over the internal
  event stream. Not planned.

## Cross-cutting requirements (apply throughout)
- Golden rules in `CLAUDE.md` — especially identity out-of-band (never regress T3).
- Tests land with code. Security tests (T3) are non-negotiable.
- Secrets referenced via env, never committed.
- Contracts (protocol/registry/node) are fixed — raise questions, don't drift.
