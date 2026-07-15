# BUILD_PLAN.md — Sequenced implementation

Build the generic gateway + widget skeleton first, then plug in bots. Do not reorder.
Each step lists deliverables and the tests that gate it.

## Status (as of 2026-07-02)

Legend: ✅ done · 🟡 in progress · ⬜ not started

- ✅ **Step 0** — repo + tooling, Docker Compose (gateway/widget/caddy), GitHub Actions CI, deployment doc (`docs/07`)
- ✅ **Step 1** — gateway skeleton (gate green: T1, T8.1–2)
- ✅ **Step 2** — widget skeleton (gate green: T10-A, T10-B)
- ✅ **Step 3** — auth path (gate green: T2)
- 🟡 **Step 4** — 4a (abuse/embedding, T9.1/2/4) ✅ · 4b (MCP identity wrapper + tool scoping, T4.1/4.3, T3.2) ✅ · 4c (real MCP server + bot, guard classifier T4.2, live T4/T9.3, T10-E) ⬜ **infra-gated** (needs a model endpoint + a backend API to wrap)
- ⏸ **Step 5** (deferred — no named auth-bot consumer) · **Step 5b** → moved to 9c ·
  ✂ **Step 6** (dissolved — bots are YAML now, see Step 9)
- 🟡 **Consolidation track (Steps 7–10)** — askUOS onto the platform: persistence (7) ✅,
  query-param passthrough (8) ✅, config-only bot authoring / stock fragments (9) ✅,
  askUOS via its OpenAI-compatible API (9a, docs/08 Scenario 3), stock router +
  front-door bot (9c, was 5b), full MCP port (9b, deferred), cutover (10). Added
  2026-07-07 from meeting requirements; 9a/9b split + step 9 added 2026-07-15; front
  door confirmed → 5b moved to 9c, Step 5 deferred, Step 6 dissolved (2026-07-15).

Verified across the done steps: gateway `pytest` + `mypy --strict` + `validate-config`;
widget Vitest + Playwright(axe) + `tsc --strict`. Work is committed on `main`.

## Step 0 — Repo & tooling  ✅
- ✅ Repo layout per `CLAUDE.md`. `uv` for gateway (py3.12), npm+Vitest+Playwright for widget.
- ✅ CI: `.github/workflows/ci.yml` runs `mypy --strict`, `pytest`, `validate-config`
  (gateway) and `tsc --strict`, `npm test`, Playwright/axe (widget), plus a docker-build job.
- ✅ Docker Compose (`gateway` + `widget` + `caddy`) + Dockerfiles + Caddyfile. vLLM/MCP/
  Keycloak are external (URLs in config), not services. See `docs/07-deployment.md`.

## Step 1 — Gateway skeleton  ✅
- Config models (Pydantic) + loader + `validate-config` CLI with checks 1–13
  (`docs/03-registry.md`). Fail boot on invalid.
- Bot registry (in-memory, typed access API).
- In-memory session store / LangGraph MemorySaver checkpointer, TTL eviction. Wire
  checkpointer ONLY in the graph factory.
- RuntimeContext builder (auth stub for now).
- Graph factory + shared skeleton (guard/decline scaffolding).
- Config models + loader + `validate-config` CLI with checks 1–13
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

**4c — the real bot  🟡 (infra-gated)**
- ✅ Real streamable-HTTP MCP transport (`app/mcp/transport.py`): tool discovery +
  tool calls; identity delivered via MCP `_meta` (NOT a tool argument — a real server
  silently drops an extra `_identity` arg; contract corrected in docs/04 §7); gateway
  bearer token via Authorization header. Tested against an in-memory FastMCP server.
- ✅ Reference bot `it-helpdesk` (`app/graphs/it_helpdesk.py`, `config/bots/it-helpdesk.yaml`):
  retrieve-then-generate over `uos_search`/`uos_fetch`, config-driven model + MCP
  connection, guard on, citations. Fragment registered. Tested end-to-end against an
  in-memory MCP server + fake model.
- ⬜ **Live run** (needs the real vLLM + MCP endpoints): set `mcp_servers.uos-docs.url`
  + `UOS_DOCS_MCP_TOKEN`, point a provider at vLLM, run the guard/T4 live and adapt
  `_parse_results`/`_page_text` to the server's real return shapes if needed.
- ⬜ **Pre-public gates:** T4.2 (guard declines live), T3.3 (indirect-injection —
  retrieved page content is untrusted), T10-E manual SR audit + conformance statement.

- **Gate:** T4 (scoping) — T4.1/4.3 ✅, T4.2 (guard declines) ⬜ needs classifier;
  T3.2 ✅. T9 (embedding/abuse) — T9.1/2/4 ✅, T9.3 ⬜. T10-E manual SR audit + publish
  conformance statement before this bot goes public ⬜.

## Step 5 — First auth bot (live own-data-only)  ⏸ DEFERRED (no named consumer)
Re-scoped 2026-07-15. The original purpose ("the generalization test": auth +
interrupts) is now covered elsewhere — the auth path is built and tested (Step 3, T2),
and the interrupt lifecycle gets its first REAL consumer in the router (Step 9c, T5).
What this step uniquely adds is **live own-data-only MCP enforcement (T3) against a
real per-user backend** — and no identity-aware bot with a real backend has been asked
for. Per the dual-API lesson (docs/02): do not build for a hypothetical consumer.
**Un-defer when** a named identity-aware use case with a real backend exists; the
enrollment-bot sketch below is the template then.
- enrollment bot: requires_auth + interrupt (quick-replies); MCP server enforcing
  own-data-only. Gate: Path A end-to-end, T3 (MANDATORY), T7 × {auth,unauth}.

## Step 5b — Orchestrator (front door)  → moved to Step 9c
The front door is confirmed wanted (2026-07-15) and is now **Step 9c** in the
consolidation track, redesigned as a *stock* `router` fragment so orchestrators are
config-only too. See the track below for the full spec (T11 gates carry over).

## Step 6 — Remaining bots  ✂ DISSOLVED into config authoring
After Step 9, a bot is one YAML file on a stock fragment (docs/09) — covered by the
per-bot conformance harness automatically. Adding bots is operations, not a build
step. Bespoke-fragment bots (novel flows) remain possible and follow docs/09 §3b.

## Consolidation track — askUOS onto the platform  ⬜

Bring the existing askUOS chatbot onto this gateway + widget, retiring its standalone
API/auth/persistence. Two new requirements (conversation persistence, query-parameter
passthrough) are built first as enabling platform work; askUOS then lands as a bot.
Decisions locked (meeting 2026-07-07): survive-reload persistence only; TTL 120 min,
configurable; both anon + auth; params are non-sensitive (untrusted `context` channel,
never identity); askUOS stays public; **Kubernetes/Redis deferred — keep the swap-point
seam, ship in-memory** (Redis stays in "Later / v2" below).

**Step 7 — Survive-reload persistence (no Redis)**  ✅
- `session_ttl_s` default → `7200` (per-bot overridable; mechanism already exists). No
  new store: in-memory MemorySaver + session store already survive reload on a single
  instance. Keep the checkpointer/session-store swap-point seam intact (Redis-ready).
- Widget: persist `session_id` + local transcript in `localStorage`; rehydrate the UI
  on reload and continue the same server session. No new protocol endpoint.
- **Gate:** reload-continuity test (reload mid-conversation → same server session +
  checkpoint reused, context retained); existing T8 (session/TTL) stays green.

**Step 8 — Query-parameter passthrough**  ✅
- Protocol: additive optional `context` object in the request body (keys `page`/`url`,
  `topic`, `locale`; size cap), documented **untrusted + non-identity**. Locale stays on
  `client.locale`/`?lang`. Update `docs/01-protocol.md`.
- Gateway: thread `context` into `turn_input`, kept separate from the identity path;
  validate schema (size/key allowlist). Inject into prompts as data-not-instructions
  (it-helpdesk reference pattern).
- Widget: read params from embed `data-*`/URL; forward in the request.
- Routing hint: bot selection = `bot_id` in path (bootstrap); topic hint rides in
  `context` until Step 9c routing lands.
- **Gate:** new T12 (context reaches graph as untrusted data; oversize/unknown keys
  rejected; no context path can populate identity — extends T3).

**Step 9 — Config-only bot authoring: stock fragments + `graph_params`**  ✅
Make the common bot (system prompt + LLM + MCP tools) a pure-YAML change — no fragment
code, no registry edit, no image rebuild. Stock fragments are generic, vetted shapes
that read everything from `BotCfg`; YAML *selects and parameterizes* them. This is NOT
graph-as-YAML (no topology in config; graphs stay code) and NOT a self-serve builder
(still ops-deployed, `validate-config`-gated, fail-fast). This step is what makes
Step 6 ("remaining bots — fast, repetitive") true, and 9a consumes its first fragment.
- **Stock `passthrough`** (docs/08 Scenario 3 shape): stream the provider with session
  history, no tools, `status("thinking")` at turn start. Built generically from day
  one — Step 9a's askUOS bot is its first consumer.
- **`graph_params`** (approved 2026-07-15): additive per-bot config block (docs/03);
  each stock fragment declares a Pydantic params model; new **validation check 14**
  rejects unknown/invalid params for the selected `graph` at boot (spirit of check 13).
  Bespoke fragments ignore it.
- **Stock `tool-agent`** (decisions locked 2026-07-15): a **bounded** model-driven
  tool loop over the allowlisted MCP tools. `graph_params.max_tool_rounds`
  **defaults to 1** — one round of tool calls, then a final generate with no tools
  bound, so by default a poisoned tool result can only influence answer *text*
  (same injection posture as it-helpdesk); raising rounds is an explicit per-bot
  opt-in that re-enters the model with tool output in context. Allowed for **auth
  bots too** (identity stays out-of-band via `_meta`; MCP server enforces
  own-data-only — T3 unaffected by fragment choice). Citations via explicit
  `graph_params.sources_from: [tool, …]` (check 14 verifies ⊆ effective allowlist;
  no magic result-shape sniffing). Auto `status("tool_call")` around calls; tool
  output framed as untrusted data in the loop and in the final generate.
- Stock `retrieve-then-generate` (parameterized it-helpdesk shape): deferred until a
  second docs-QA bot appears (rule of three); it-helpdesk itself stays bespoke —
  deterministic hand-written flow is the stronger guarantee.
- Docs: rewrite `docs/09-adding-a-bot.md` around "config-only is the default path;
  write a fragment only when the flow is novel"; docs/03 gains `graph_params`.
- Ops story: bot change = edit YAML → `validate-config` in CI → restart (atomic,
  fail-fast; config is volume-mounted). Hot-reload deliberately deferred to Later/v2.
- **Gate:** a sample config-only bot boots with zero code changes; check 14 rejects
  bad params (incl. `sources_from ⊄ allowlist`); T4 allowlist tests hold for stock
  fragments; **T7 conformance harness runs against every enabled bot automatically**
  (fake model + fake MCP — config-only bots have no bot-specific test code);
  docs/09 updated.

**Decision note — bot deployment decoupling & fragment extensibility** (decided
2026-07-15; also the answer to "make the gateway generic for other institutions"):

*Already true:* config is volume-mounted (`./config:/config:ro`), so config-only
bots deploy with **no image rebuild** — YAML change + restart. Restart drops
in-memory sessions (T8.2); frequent bot deploys strengthen the case for the Redis
checkpointer swap (Later/v2).

*The extension model is **config + external services + a growing stock library**:*
- **(C) Bot logic lives outside the gateway** behind the two sanctioned seams — MCP
  servers (with stock fragments in front) or Scenario-3 OpenAI-compatible endpoints.
  Institution-owned services deploy on their own lifecycle; the gateway stays a
  stable, generic, versioned product artifact. Per golden rule 7 (single-tenant),
  "other institutions" means *their own deployment* of that artifact, never a shared
  multi-tenant instance.
- **(D) Stock fragments grow by rule-of-three promotion:** recurring bespoke shapes
  are promoted to parameterized stock fragments (`graph_params`) and arrive via
  normal upstream image upgrades. Params configure a *fixed* shape only — topology
  in config (graph-as-YAML) remains a hard non-goal.
- **Known gap to watch:** interactive flows (interrupts/quick-replies) cannot cross
  the C seam today. If an external-institution bot genuinely needs them, the fix is
  an additive tool-result→interrupt convention in the stock fragments — not a
  plugin mechanism.

*Rejected / blocked paths for bespoke code:*
- **Mounted plugin directory (dynamic import): REJECTED.** Untested code inside the
  trust boundary — skips mypy/pytest and the T3/T4 security gates; fragments hold
  `RuntimeContext` (identity), and Python has no in-process sandbox.
- **Plugin packages + derived image (pip/entry-points): BLOCKED as policy** — last
  resort only, revisited solely if C+D demonstrably cannot cover a real case. Its
  hidden cost is promoting `BotGraphBuilder`/`BotState`/`emit_*`/`mcp_call` to a
  semver-stable public API plus shipping the security-test kit for plugin CI.
- Bespoke fragments therefore remain **in-tree gateway code → image rebuild by
  design** (the rebuild IS the CI-tested artifact), and rare by policy.

**Step 9a — askUOS via its OpenAI-compatible API (docs/08 Scenario 3)**  ⬜
The cheap path first: askUOS already exposes `/v1/chat/completions`, and the gateway
consumes OpenAI-compatible endpoints natively (that's how it talks to vLLM). This
consolidates the *frontend layer* (one widget, one gateway: sessions, rate limits,
origin gates) while askUOS's backend keeps running unchanged as a second service.
- Config only, no gateway change: `model_providers.askuos` (`base_url` → askUOS `/v1`,
  `api_key_env: ASKUOS_API_KEY`, generous `timeout_s` — search/crawl turns are slow);
  `config/bots/askuos.yaml` (`model.provider: askuos`, `tools.mcp_servers: []`,
  `requires_auth: false`, minimal/empty `prompt.system` — askUOS injects its own).
- Uses the **stock `passthrough` fragment from Step 9** (`graph: "passthrough"`) — no
  bot-specific fragment code; askUOS emits nothing during its retrieval phases, so the
  stock fragment's `status("thinking")` covers the dead air.
- Decisions locked: **stateless history** (send gateway history each turn — standard
  OpenAI, no coupling to askUOS's custom `thread_id`; `history_max_turns` caps it;
  askUOS trims to its own last-7 internally). **`language` via `extra_body`** (the one
  non-standard field worth taking; defaults German otherwise). **Guard** enabled once
  live model infra exists (check-7 warning accepted until then; askUOS's own judge
  nodes decline off-topic in the interim).
- Accepted losses (documented, revisit in 9b): citations arrive as markdown *text*
  appended by askUOS, not `sources` cards; step-8 `context` is validated by the gateway
  but dropped (askUOS's API has no such field); the external service is trusted
  wholesale — no MCP structural scoping (docs/08 Scenario 3 caveat; acceptable for a
  university-owned service on public data).
- **Gate:** fragment + config tested against a fake OpenAI-compatible endpoint (fake
  streaming provider, like the it-helpdesk tests); T1/T7 conformance for the bot; live
  run infra-gated on the askUOS URL + key only.

**Step 9c — Stock `router` fragment + the front-door bot (was Step 5b)**  ⬜
The front door is a named requirement (2026-07-15). Redesigned post-step-9: the router
is a **stock fragment** driven by the existing `routes:` config block (validation
checks 10–12 sit ready), so the orchestrator itself is **config-only** — the target
picture is two YAML files: the front-door bot + the askUOS bot (9a).
- Stock `router` fragment: composes the routed bots' fragments as subgraphs
  (docs/04 §6b), **menu-first** via `quick_replies` (the first real consumer of the
  interrupt machinery — T5 lands here, not in deferred Step 5), sticky routing after
  a choice. Activates checks 10–12 (targets exist; public router → public targets
  only; embedding-mode sanity). `GraphCache` loses its `routes` NotImplementedError.
- Front-door bot = one YAML: `graph: "router"`, `routes:` → [askuos (9a),
  it-helpdesk, campus-search, …]. Handoffs are ordinary `text`; menu is
  `quick_replies` — no protocol change (docs/01 explicitly anticipates this).
- Not infra-gated: testable against fake sub-bots (conformance harness covers the
  front-door bot automatically once enabled).
- **Gate:** T11 (routing) + T5 (interrupt lifecycle) + Path C end-to-end; T11.6
  (sub-bot scoping unchanged when reached via the router); check 10–12 tests.

**Step 9b — Full port: askUOS as a first-class bot (MCP + fragment)**  ⬜ (deferred —
decide after 9a has run; do it when the 9a gaps bite: context passthrough, real
citation cards, retiring the separate askUOS deployment)
- Wrap askUOS retrieval (RAGFlow client, web-search + crawler, doc grading) as MCP
  server(s); askUOS's own Redis search-cache stays inside that MCP server.
- Port askUOS's self-RAG graph (agent→judge→tools→grade→generate/rewrite) as a graph
  fragment; map state onto `BotState`+`scratch`; allowlist the MCP tools; reuse DE/EN
  prompts; `requires_auth: false`, guard on. Register the fragment.
- Retire askUOS's OpenAI API, static-key auth, and bespoke persistence.
- **Gate:** T3 (identity isolation), T4 (scoping), T3.3 (indirect-injection — retrieved
  content untrusted), T4.2 (guard declines), T7 conformance. Needs live model + RAGFlow
  endpoints (infra-gated like Step 4c).

**Step 10 — Cutover**  ⬜
- Run gateway-hosted askUOS (9a passthrough) side-by-side with the standalone service's
  own frontend; point widget/embeds at the gateway; validate parity (DE/EN, citations,
  retrieval quality). Note: the standalone askUOS *service* stays up (9a depends on it) —
  only its separate frontend surface is retired. Full decommissioning happens with 9b.

## Later / v2 (do not build now)
- Free-text classifier routing fallback (`routes.mode: classifier`) with a cheap model
  + "finding the right assistant…" status. Menu-first ships in v1.
- Dynamic mid-conversation re-routing (topic switch detection).
- Forms: additive `form` event + widget + a11y, when a concrete bot needs structured
  multi-field input.
- Redis checkpointer for horizontal scaling (one-line swap in the graph factory).
- Config hot-reload (admin reload endpoint / SIGHUP). Restart-on-change is atomic and
  fail-fast today; hot-reload adds cache-invalidation + in-flight-session questions.
- Optional per-bot audit logging; observability (structured per-turn logs, metrics).
- (Only if a real consumer appears) an OpenAI-compatible translator over the internal
  event stream. Not planned.

## Cross-cutting requirements (apply throughout)
- Golden rules in `CLAUDE.md` — especially identity out-of-band (never regress T3).
- Tests land with code. Security tests (T3) are non-negotiable.
- Secrets referenced via env, never committed.
- Contracts (protocol/registry/node) are fixed — raise questions, don't drift.
