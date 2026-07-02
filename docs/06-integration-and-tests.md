# 06 — Integration Spec & Test Plan

Two hardest end-to-end paths + full test plan. If both paths work, the architecture
is proven.

## Path A — Native: auth + tool call + interrupt + resume

note routing is exercised elsewhere

### A1 — first request (bot disambiguates via quick-replies)
```
Widget → Gateway: POST .../bots/enrollment/chat  Authorization: Bearer <tok>
                  { message: "check my credits" }
Gateway → Keycloak: validate token → claims {sub}
Gateway: build RuntimeContext(identity, surface=native); new session s1;
         check origin allowed + rate ok
Gateway → Widget: event session {session_id:s1, seq:0}
Gateway → LangGraph: astream(input={kind:text}, ctx)
  guard: in-scope; emit status(thinking)
Gateway → Widget: event status {seq:1}
  agent: ask_quick_replies(...) → __interrupt__
Gateway: assign reply_to=evt_88; checkpoint state
Gateway → Widget: event quick_replies {reply_to:evt_88, options, seq:2}
Gateway → Widget: event done {status:awaiting_input, seq:3}   [stream closes]
```
Assertions: token validated before graph exec; `identity.subject` in ctx not
BotState; gateway assigns reply_to; exactly one `done`.

### A2 — resume (user picks option, MCP tool call, answer)
```
Widget → Gateway: POST ...  { session_id:s1, choice:{id:credits}, reply_to:evt_88 }
Gateway → Keycloak: validate token (fresh)
Gateway: load checkpoint s1; verify reply_to matches pending interrupt
         (else no_pending_interrupt)
Gateway → Widget: event session {seq:0}
Gateway → LangGraph: Command(resume={kind:choice,id:credits})
  emit status(tool_call); mcp_call(ctx, get_my_credits)  [_identity injected]
    MCP re-validates sub; enforces own-data-only
Gateway → Widget: event status; then text deltas (message_id:m1)
  graph → END
Gateway → Widget: event done {status:complete}
```
Assertions: reply_to mismatch → no_pending_interrupt (no double execution); identity
out-of-band; MCP re-validates; token re-validated on resume (token_expired triggers
host refresh).

## Path C — Orchestrator (front door → sub-bot, sticky)

```
Widget → Gateway: POST .../bots/assistant/chat  { greeting: true }
Gateway: session s1; run router graph (bot_greeting)
  menu node → ask_quick_replies([Courses, Library, General questions])
Gateway → Widget: quick_replies {reply_to:evt_1, options}; done: awaiting_input

Widget → Gateway: POST .../bots/assistant/chat
                  { session_id:s1, choice:{id:course-catalog}, reply_to:evt_1 }
Gateway: resume; scratch.route = course-catalog (sticky); enter subgraph
  course-catalog subgraph runs (status → tool → text → sources)
Gateway → Widget: status; text deltas; sources {message_id:m1}; done: complete

Widget → Gateway: POST .../bots/assistant/chat
                  { session_id:s1, message:"is CS110 a prerequisite?" }
Gateway: sticky → re-enter course-catalog subgraph directly (no menu)
Gateway → Widget: text …; done: complete
```
Assertions: menu routes correctly; sticky keeps follow-ups in the sub-bot; a sub-bot
interrupt inside the composite resumes correctly (composite checkpoint); a **public**
router has no route to any auth bot (config check 11 — assert at validate-config).

## Test Plan

### T1 — Protocol conformance
1. First turn no session_id → stream starts with `session` minting new id.
2. Exactly one `done`; seq monotonic from 0.
3. Two input fields → 400 invalid_request, no stream.
4. Over-length → 400 message_too_long.
5. Unknown bot → 404 unknown_bot.
6. choice with no pending interrupt → no_pending_interrupt.
7. Heartbeat during delayed tool call.

### T2 — Auth path
1. Missing token on auth bot → 401, no graph exec.
2. Expired token → token_expired (recoverable).
3. Valid token → identity.subject in ctx, ABSENT from checkpoint (inspect it).
4. Missing role → forbidden.
5. Token expiry between interrupt and resume → token_expired on resume, session
   survives, retry after refresh works.

### T3 — Identity isolation (MANDATORY, security-critical)
1. **Cross-user access:** auth as X, try to fetch Y's data via crafted free text /
   injection → MCP refuses; no Y data in response. Assert at gateway (no Y in tool
   args) AND MCP (rejects mismatched subject).
2. **Model-authored identity:** tool's model-visible signature has no identity param
   (introspection test) — model cannot supply one.
3. **Indirect injection:** MCP returns "ignore previous instructions…" → model does
   not act on it; tool output delimited as data.

### T4 — Scoping
1. Read-only bot's compiled graph has no edge/tool to any write tool (structural).
2. Guard declines a curated out-of-scope set for guard-enabled bots.
3. Denylist precedence: tool in allow+deny is unavailable.

### T5 — Interrupt lifecycle
1. Quick-reply round-trip (A1→A2) resumes correct state/answer.
3. reply_to mismatch → no_pending_interrupt; MCP called exactly once (spy).
4. Second interrupt before resolving first → rejected (one pending at a time).
5. Interrupt inside a routed subgraph resumes correctly via the composite checkpoint (Path C)

### T7 — Graph conformance harness (run for EVERY bot × {auth, unauth})
1. Operates only on BotState.
2. Reads identity only from ctx (no state["identity"]).
3. Emits via helpers only (status/sources/quick_replies; text via model node).
4. All MCP calls via identity-injecting wrapper.
5. Every path reaches END.
6. For routers: every reachable subgraph's tool allowlist is intact; auth posture holds.

### T8 — Session & scaling
1. TTL eviction → session_not_found; widget starts fresh gracefully.
2. Restart drops sessions → widget handles session_not_found without crashing.
3. [Redis checkpointer] identical behavior; sessions survive restart.

### T9 — Embedding & abuse
1. Origin not in allowed_origins → 403 forbidden_origin.
2. Rate limit exceeded → 429 with retry_after.
3. Per-session token/cost cap for anonymous public bots.
4. CORS preflight correct for allowed origins only.

### T10 — Widget accessibility
See `docs/05-accessibility.md` §11 (T10-A…E). T10-E is a pre-launch gate.

### T11 — Routing / orchestration
1. Menu selection routes to the correct subgraph.
2. Sticky routing: follow-up turn re-enters the same sub-bot without re-showing menu.
3. "Ask about something else" returns to the menu.
4. validate-config FAILS a public router that lists an auth-bot target (check 11).
5. validate-config FAILS a router targeting a missing/self/disabled bot (check 10).
6. Sub-bot's tool allowlist is unchanged when reached via the router (structural scope
   preserved — no cross-sub-bot tool access).

## "Done" for build-step 5

- Path A passes end-to-end (T2, T3, T5 green).
- T7 harness passes for both real bots across all four parameter combos.
- T3 passes (cannot ship without).

At that point the generic skeleton is proven by a second, structurally different bot;
bots 3–5 are repetitive config+graph+MCP work.
