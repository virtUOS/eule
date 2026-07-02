# 01 — Chat Protocol v1 (Widget ↔ Gateway)

The rich, native wire contract. The OpenAI adapter (`02-dual-api.md`) is a lossy
projection of this.

## Principles

- One request → one SSE stream, terminated by exactly one `done`.
- Server owns session and state; client never invents `session_id` or sends history.
- Events are typed and forward-compatible; unknown types/fields are ignored, never fatal.
- Interrupts map to LangGraph `interrupt`/resume.
- **Routing needs no protocol change.** An orchestrator bot uses the same events;
  its menu is `quick_replies`, its handoffs are ordinary `text`.

## Transport

- `POST /api/v1/bots/{bot_id}/chat`
- Request body: `application/json`
- Response: `text/event-stream` (SSE)
- Auth: `Authorization: Bearer <token>` header when the bot has `requires_auth`.
  **Never in the body.**
- **Client uses `fetch` + `ReadableStream`**, not `EventSource` (POST + auth header).
- Gateway sends `: ping\n\n` heartbeat every ~15s during long operations.

### SSE framing

```
event: <event_type>
data: <single-line JSON>

```

`data` is always single-line JSON (newlines escaped). Blank line terminates.

## Versioning

- Major version in path (`/api/v1/`).
- First event of every stream is `session`, carrying `protocol_version` (semver).
  Clients check major; minor bumps are additive-only.

## Request schema

```jsonc
{
  "session_id": "9b0f...",   // omit on first turn; required afterwards
  // exactly ONE of:
  "message": "How many credits is CS101?",
  "choice":  { "id": "opt_credits" },

  "reply_to": "evt_7c21",    // required when replying to a choice; echoes prompting event
  "greeting": false,         // optional; true = run bot's greeting node (see §Conversation start)
  "client": { "locale": "en", "widget_version": "1.4.2", "embed_origin": "https://x.uni.edu" }
}
```

Rules:
- First turn: no `session_id`; `message` present (or `greeting:true`).
- Resume: `session_id` + `choice` + matching `reply_to`.
- `choice` with no pending interrupt → `error` `no_pending_interrupt`.
- More than one input field → `400 invalid_request`.

## Server → client events

Every payload includes `{ "type": "...", "seq": <int> }`. `seq` is monotonic per
stream from 0.

### `session` (always first, seq 0)
```jsonc
{ "type":"session","seq":0,"session_id":"9b0f...","protocol_version":"1.0",
  "bot_id":"course-catalog","expires_in":1800 }
```

### `status` (ephemeral progress)
```jsonc
{ "type":"status","seq":3,"state":"tool_call","label":"Checking course catalog…",
  "detail":"course-catalog.search" }
```
`state`: `thinking | tool_call | done_thinking`. `label` is user-facing/localized.
`detail` is a machine hint, not shown raw. No pairing guarantee; superseded by next
`status`/`text`/terminal event.

### `text` (streamed tokens)
```jsonc
{ "type":"text","seq":4,"message_id":"m1","delta":"CS101 is " }
```
Concatenate deltas with same `message_id` in `seq` order. New `message_id` = new bubble.

### `quick_replies` (interrupt awaiting a choice)
```jsonc
{ "type":"quick_replies","seq":7,"reply_to":"evt_7c21","prompt":"What next?",
  "options":[{"id":"opt_credits","label":"Check credits"}],
  "allow_free_text":true }
```
After this, graph is interrupted; stream ends with `done: awaiting_input`. The
choice arrives as a fresh POST.

### `sources` (retrieval attribution, at most once per assistant message)
```jsonc
{ "type":"sources","seq":8,"message_id":"m1",
  "sources":[
    { "title":"VPN-Einrichtung — Rechenzentrum",   // card title  (mockup: label)
      "source":"uni-osnabrueck.de",                 // card subtitle (mockup: host)
      "url":"https://…" }
  ] }
```
- Emitted at most once per assistant message, after its `text`, before `done`.
- `sources` is a flat list of `{title, source, url}` (`source` = the host/subtitle
  shown under the title on the citation card) — **no per-claim attribution** (honest and
  simple: these are what the retrieval/tool step returned, or a subset the node chose).
- The widget renders a labelled **"Sources" footer** under the message (appearance is
  the widget's business; a card style is fine).
- Accessibility: announced as a labelled list *after* the message body (see
  `05-accessibility.md`), not interleaved into the streamed text.
- `message_id` ties the sources to the bubble they belong to.

### `error`
```jsonc
{ "type":"error","seq":9,"code":"tool_unavailable","message":"…user-facing…",
  "recoverable":true,"retry_after":5 }
```
May arrive after partial `text` (keep rendered text, append error). Followed by a
terminal `done: error`.

### `done` (terminal, exactly one per stream)
```jsonc
{ "type":"done","seq":12,"status":"complete","session_id":"9b0f...","expires_in":1800 }
```
`status`: `complete` (re-enable input) | `awaiting_input` (resume with `reply_to`)
| `error`. Missing `done` = transport failure (client-side).

## Error codes

| code | HTTP (pre-stream) | recoverable | meaning |
|---|---|---|---|
| `invalid_request` | 400 | false | Malformed / multiple input fields. |
| `message_too_long` | 400 | false | Over per-bot limit. |
| `unknown_bot` | 404 | false | Not in registry. |
| `unauthorized` | 401 | false | Missing/invalid token. |
| `token_expired` | 401 | true | Host should refresh + retry. |
| `forbidden_origin` | 403 | false | Origin not in allowlist. |
| `rate_limited` | 429 | true | Includes `retry_after`. |
| `no_pending_interrupt` | in-stream | false | choice with nothing to resume. |
| `session_not_found` | in-stream | false | Unknown/expired session; start fresh. |
| `tool_unavailable` | in-stream | true | MCP/backend failure. |
| `model_error` | in-stream | true | Upstream model timeout/error. |
| `internal_error` | in-stream | false | Catch-all. |

Pre-stream errors return the HTTP status with a JSON body of the same shape
(minus SSE framing) so clients have one error model.

## Conversation start

Per-bot config (`flows.greeting.mode`):
- `client_initiated` (default): first user message opens the conversation.
- `bot_greeting`: client POSTs `{ "greeting": true }`; graph runs its intro node,
  may emit `text` and/or `quick_replies` immediately.

## Reconnection & idempotency (v1 limitations)

- Session lives server-side; client holds only `session_id`.
- On transport drop after partial `text`, client does NOT auto-replay (tool
  side-effect risk); surface a retry affordance instead.
- Replaying a `choice` after a drop is safe: `reply_to` no longer matching
  the pending interrupt → `no_pending_interrupt` (fails safe, no double execution).
- **No mid-stream resume / `Last-Event-ID`.** Dropped stream = failed turn.
- One pending interrupt per session at a time.

## LangGraph mapping (implementation)

- `text` ← model node tokens (`stream_mode="messages"`).
- `status` ← `get_stream_writer()` custom events around tool nodes.
- `sources` ← `emit_sources(...)` custom event (see `04-node-contract.md` §3).
- `quick_replies` ← `interrupt(payload)`; gateway assigns `reply_to`, emits the event,
  ends with `done: awaiting_input`.
- Resume ← incoming choice → `Command(resume=...)`.
- Identity ← injected via context, never model-authored.
- Session store ← LangGraph checkpointer keyed by `session_id`; in-memory for v1,
  TTL-evicted; swappable for Redis.

## Widget bootstrap

`GET /api/v1/bots/{bot_id}/config?lang=de` — public, CORS-checked against the bot's
`embedding.allowed_origins`, cacheable (ETag). Returns presentation-only config (no
secrets): `{ name, theme:{light,dark,dark_mode,radius}, starter_replies, greeting }`.
The widget fetches this once on load, then applies theme tokens into its Shadow root
and renders starter chips. UI chrome strings are bundled in the widget (de/en), not served.
