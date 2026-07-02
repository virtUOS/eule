# 00 — Overview & Architecture

## Problem

3–5 narrowly-scoped support chatbots (course catalog, enrollment, FAQ, …), each
backed by an OpenAI-compatible model, each calling internal APIs/DBs as tools,
embeddable in the public website and internal tools, with a simple chat UI that
also supports quick-reply choices and simple forms. Self-hosted.

Three independent concerns:
1. **Embeddable widget** (presentation) — hand-built.
2. **Orchestration** (agent logic, tools, scoping, identity) — LangGraph + FastAPI.
3. **Tools** (internal APIs) — MCP servers.

## Architecture

```
Embedded widget  ──POST /api/v1/bots/{id}/chat (SSE)──►  Gateway (FastAPI)
                                                          ├ bot registry (config)
                                                          ├ in-memory sessions (TTL)
                                                          ├ auth (Keycloak) [if required]
                                                          ├ LangGraph runner
                                                          └ OpenAI-compatible model
                                                                │ MCP (HTTP)
                                                                ▼
                                                          MCP servers (per backend)
                                                          └ enforce authz server-side
```

A second API surface (v2) exposes each bot as an OpenAI-compatible model for
third-party frontends. See `docs/02-dual-api.md`.

## Tenancy — single-tenant, replicated (decided)

**One deployment serves one tenant.** A tenant is a university or an external client.
Multiple clients = multiple independent deployments (own Docker Compose, own config
repo, own MCP servers, own Keycloak realm, own theme). The *software* is identical
across deployments; instances are isolated.

This absorbs "~10 bots + external clients" as **more instances, not a heavier system**:
- Config stays git-managed per instance (no admin UI / config API).
- In-memory single-instance sessions remain valid per deployment.
- No tenant-scoping in registry, session store, or rate limiting.

**Do NOT** add multi-tenancy (one deployment serving many clients' bots). That is a
different, much larger product (needs admin tooling, shared+isolated session store,
tenant authz). If hosted multi-tenancy is ever required, it's a deliberate future
project layered on top — not a v1 assumption to sprinkle in. Assuming it silently in
some places and single-tenant in others is the exact failure these docs prevent.

### Scaling note
~10 bots on one instance is fine for logic, but raises the chance a busy deployment
hits the single-instance session ceiling. Keep the checkpointer swap point (graph
factory, `04-node-contract.md` §6) genuinely one-line so Redis can drop in per
deployment without touching bots.

## The contracts (read the one you need)

| Doc | Contract |
|---|---|
| `01-protocol.md` | Widget ↔ gateway wire protocol (SSE events). |
| `02-dual-api.md` | REMOVED (tombstone). OpenAI adapter was cut. |
| `03-registry.md` | Bot/global config schema + validation. |
| `04-node-contract.md` | Internal LangGraph interface every bot satisfies. |
| `05-accessibility.md` | Widget WCAG 2.1 AA spec. |
| `06-integration-and-tests.md` | End-to-end sequences + full test plan. |
| `07-deployment.md` | Deployment topology, widget delivery, external-service config. |
| `08-integration-scenarios.md` | How to plug a backend in (MCP / RAG / OpenAI-compatible / migrate). |
| `BUILD_PLAN.md` | Sequenced implementation steps. |
| `design/widget-mockup/` | Visual/interaction design reference + standalone demo. |

## Scoping is enforced at three layers

1. **Tool allowlist per bot** — a bot's graph has no edge to tools outside its
   allowlist. Structurally incapable, not merely instructed.
2. **Predefined-choice flows** — button/form graph nodes sidestep open-ended scope.
3. **Guard node** (config-gated, recommended for public bots) — cheap
   classification declines out-of-scope input before the main model call.

## Orchestration & routing (front door + direct embed)

The gateway serves every bot at `/api/v1/bots/{bot_id}/chat`, and the widget targets
a bot via `data-bot-id`. This gives **two routing modes with one mechanism**:

- **Direct (context-routed):** a page embeds a specific bot
  (`data-bot-id="course-catalog"`). The user talks straight to it. Website context =
  which `data-bot-id` the embed uses. Already fully supported; nothing special.
- **Front door (orchestrated):** a page embeds an orchestrator bot
  (`data-bot-id="assistant"`) that routes to the ~10 sub-bots.

**An orchestrator is just a bot.** It's a registry entry whose graph routes to other
bots by composing their fragments as **subgraphs** — same driving loop, same protocol,
same session model. No new gateway concept, no protocol change, no widget change.

Design rules (enforced in `03`/`04`):
1. **Menu-first, not classifier-first.** v1 orchestrator opens with a quick-reply menu
   ("What can I help with? [Courses][Enrollment][…]"). Zero misrouting, zero added
   latency. A free-text classifier fallback (cheap model) is a v2 add, not v1.
2. **Compose subgraphs; never merge tool lists.** Each sub-bot keeps its own topology
   and tool allowlist, so structural scoping survives. The union is a switchboard to
   many narrow bots, not one broad bot.
3. **Auth posture is inherited and validated.** A router may only route to bots whose
   `requires_auth` ≤ the router's. A public front door structurally cannot dispatch to
   an auth bot; it hands off ("please use the authenticated portal") instead.
4. **Sticky routing per session** with an "Ask about something else" escape. Dynamic
   mid-conversation re-routing is v2.

## Identity flows out-of-band

For `requires_auth` bots: gateway validates the bearer token against Keycloak,
extracts claims, and passes them via `RuntimeContext` into tool calls. The MCP
tool enforces "you may only see your own data" — holding even if the model is
induced to ask for someone else's. See `04-node-contract.md` §7.

## Key decisions

| Area | Decision |
|---|---|
| Orchestration | LangGraph, uniform graph shape for every bot. |
| Tools | MCP servers, one per backend, shared across bots. |
| Gateway | Single FastAPI process serving all bots via config. |
| Widget | Hand-built vanilla TS, Shadow DOM, single `<script>`, **token-based theming** (design-system defaults, per-deployment overrides). |
| Tenancy | Single-tenant, replicated. One deployment per client. |
| Routing | Direct embed (`data-bot-id`) or an orchestrator bot (subgraph composition). |
| Persistence | None. In-memory sessions, TTL-evicted. (Single-instance ceiling — see below.) |
| Identity | Per-bot `requires_auth`; auth bots are internal-tool-only, never public. |
| Transport | SSE streaming incl. intermediate status events. |
| Accessibility | WCAG 2.1 AA, built into the widget from the start. |
| Hosting | Self-hosted, Docker Compose, Keycloak OIDC. |

## Scaling ceiling (documented decision)

In-memory session state = **single gateway instance** for v1. Horizontal scaling
requires a shared checkpointer (Redis). The LangGraph checkpointer is wired in ONE
place (the graph factory, `04-node-contract.md` §6) so this swap is a one-line
change later. On restart, sessions drop — the widget must handle
`session_not_found` gracefully.

## Non-goals (v1)

- No conversation persistence / cross-session memory.
- No self-serve bot creation by non-technical staff (config is git-managed).
- No public-facing identity-aware bots.
- No general-purpose multi-tenant platform (single-tenant, replicated — see Tenancy).
- No graph definitions as config data (graphs live in code).
- No OpenAI-compatible API surface (cut; see `02` tombstone).
- No forms — quick-replies + free text only (forms are an additive future event).
