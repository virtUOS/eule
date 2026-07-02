# 04 — LangGraph Node Contract (internal bot interface)

Makes "add a bot = config + graph fragment + MCP" repeatable. The gateway drives
every bot identically; all variation lives inside the graph fragment.

## Three shared contracts

A graph is conformant iff it uses ONLY: the state schema, the runtime context, and
the emission helpers. Anything else is a bug.

## 1. State schema

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class BotState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    turn_input: dict     # normalized input for this turn (see §5)
    scratch: dict        # bot-private, not part of the external contract
```

- **Identity is NOT in state.** It lives in RuntimeContext so it can never be
  model-authored or serialized into a checkpoint. (Enforcement of the golden rule.)
- `messages` is the only persisted conversation surface. `history_max_turns` applied
  by the gateway when hydrating, not by the graph.

## 2. Runtime context (injected, read-only)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Identity:
    authenticated: bool
    subject: str | None      # trusted subject_claim value
    claims: dict
    roles: list[str]

@dataclass(frozen=True)
class RuntimeContext:
    bot_id: str
    config: "BotCfg"
    identity: Identity
    session_id: str
    request_id: str
    locale: str | None
    # NOTE: no `surface` field. The OpenAI surface was cut; there is one surface.
```

Injected via `graph.astream(..., config={"configurable": {"ctx": ctx}})`. Read-only;
never written by nodes; never in a checkpoint; invisible to the model.

## 3. Emission helpers (only sanctioned event producers)

```python
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

def emit_status(state: str, label: str, detail: str | None = None):
    get_stream_writer()({"type":"status","state":state,"label":label,"detail":detail})

def emit_sources(message_id: str, sources: list[dict]):
    # sources: [{"title": str, "source": str, "url": str}], once per assistant message
    get_stream_writer()({"type":"sources","message_id":message_id,"sources":sources})

# text is emitted implicitly by streaming the model node (stream_mode="messages").

def ask_quick_replies(prompt: str, options: list[dict], allow_free_text: bool = True) -> dict:
    return interrupt({"interrupt_kind":"quick_replies","prompt":prompt,
                      "options":options,"allow_free_text":allow_free_text})
```

- Gateway assigns `reply_to` when translating the interrupt to a protocol event; the
  graph never sees it. On resume, gateway validates `reply_to` and feeds the
  normalized reply back as the `interrupt()` return value via `Command(resume=...)`.
- When `ctx.surface == "openai"`, `allow_free_text=False` is illegal (rejected at
  config validation, asserted at runtime as defense-in-depth).
- `allow_free_text` is now a pure per-interrupt UX choice (let the user type instead of
  clicking a chip). It is NOT a cross-surface obligation — the OpenAI surface is gone.
- `emit_sources` typically runs after a retrieval/MCP tool node, passing through the
  `{title,source,url}` list the tool returned (or a curated subset). Do not fabricate
  sources. `message_id` MUST be the `.id` of the AIMessage the sources belong to (the
  same id the model streamed `text` deltas under) — the gateway maps it to the
  client-facing bubble id; passing any other value misattaches the sources.
- **`ask_form` removed.** Forms are not in v1. If a bot needs structured multi-field
  input, raise it — it's an additive protocol event, not a workaround.

## 5. Normalized turn input

Gateway normalizes every request before the graph:

```python
{"kind":"text","text":"How many credits is CS101?"}
{"kind":"choice","id":"opt_credits","text":None}       # button pressed
{"kind":"choice","id":None,"text":"check my credits"}  # free-text alternative
```

First turn: placed in `state["turn_input"]` + appended to `messages`. Resume: delivered
as the `interrupt()` return value. Interrupt nodes should handle both a clicked choice
(`id` set) and — if `allow_free_text` — a typed reply (`id` None, `text` set) via
`resolve_choice`.

## 6. Standard graph skeleton

```
guard (optional) ──in-scope──► agent/flow ──► END
      └──out-of-scope──► decline ──► END
```

Shared factory builds the outer skeleton; bots supply only the middle:

```python
def build_bot_graph(cfg, mcp_tools, flow):
    g = StateGraph(BotState)
    if cfg.guard.enabled:
        g.add_node("guard", make_guard_node(cfg))
        g.add_node("decline", make_decline_node(cfg))
    flow.attach(g)                       # bot-specific nodes/edges
    return g.compile(checkpointer=gateway_checkpointer)   # ONLY place checkpointer is wired
```

The checkpointer lives here only — swapping MemorySaver → Redis is a one-line change,
invisible to bots.

## 6b. Orchestrator bots (subgraph composition)

An orchestrator is a bot whose fragment **composes other bots' fragments as
subgraphs** — it does NOT merge their tools. This preserves each sub-bot's structural
scoping (a sub-bot still has no edge to another sub-bot's tools).

Rules:
- Build each sub-bot's fragment once; the router `add_node`s each as a subgraph and a
  router node dispatches to the selected one.
- **Menu-first (v1):** the router's entry is a `bot_greeting` that calls
  `ask_quick_replies` with one option per `routes.targets[]`. The chosen `id` selects
  the subgraph.
- **Sticky routing:** store the chosen route in `scratch` (or a reserved session key);
  subsequent turns re-enter the same subgraph. Provide an "Ask about something else"
  option to return to the menu.
- **Auth posture** is enforced at config validation (registry check 11); the router
  graph may assume every target it can reach is auth-compatible with its context.
- **Interrupts across routing just work:** the composed graph is one compiled graph
  with one checkpoint per `session_id`; a sub-bot's `quick_replies` pauses and resumes
  inside the composite state with no special routing logic on resume. (Test it — it's
  inherent, not built. See `06` §T5.)

```python
def build_router(cfg, subgraph_fragments: dict[str, GraphFragment]):
    def flow(g):
        def menu(state, *, ctx):
            reply = ask_quick_replies(
                "What can I help with?",
                [{"id": t.bot, "label": t.label} for t in cfg.routes.targets],
                allow_free_text=False,          # v1: menu only; classifier is v2
            )
            route = resolve_choice(reply, valid_ids={t.bot for t in cfg.routes.targets})
            return {"scratch": {"route": route}}
        g.add_node("menu", menu)
        for target, frag in subgraph_fragments.items():
            g.add_node(target, frag.compiled_subgraph())
        g.add_conditional_edges("menu", lambda s: s["scratch"]["route"],
                                {t: t for t in subgraph_fragments})
        for target in subgraph_fragments:
            g.add_edge(target, END)
    return GraphFragment(flow)
```

## 7. Tool calling with out-of-band identity (SECURITY-CRITICAL)

Identity travels via MCP's **`_meta` request field**, NOT as a tool argument. This is a
correction to the original arg-based design: a real MCP server (e.g. FastMCP) **silently
drops** an unknown `_identity` argument, so the identity would vanish en route and
own-data-only enforcement would be impossible — a security failure. `_meta` is transport
metadata, structurally outside the tool's `inputSchema`, so the model can neither author
nor name it (a *stronger* guarantee than a specially-named argument).

- The model-visible tool schema is EXACTLY the tool's declared inputs — no identity
  field. The model cannot supply someone else's id.
- All MCP calls go through ONE wrapper (`app/mcp/client.py::mcp_call`) that passes the
  model's args as tool `arguments` and the trusted identity separately (→ `_meta`):

```python
async def mcp_call(ctx, client, tool_name, **model_args):
    return await client.call(
        tool_name,
        arguments=dict(model_args),   # model-authored → tool `arguments`
        identity={"subject": ctx.identity.subject, "claims": ctx.identity.claims},  # → _meta
    )
```

The concrete transport (`app/mcp/transport.py::StreamableHttpMcpClient`) sets
`session.call_tool(name, arguments, meta={"identity": ...})`. The gateway's static bearer
token (authenticating the gateway to the server — `mcp_servers.bearer_token_env`) rides
the HTTP Authorization header, a separate concern from `_meta` identity.

- The MCP server reads identity from `_meta` (e.g. FastMCP: `ctx.request_context.meta`),
  re-validates it, and enforces "own data only" (defense in depth). A value the model
  smuggles into `arguments` (e.g. `subject=...`) is NOT identity and must be ignored for
  authz.
- Tool-returned content is UNTRUSTED (indirect prompt injection). The model prompt
  clearly delimits tool output as data, not instructions.

## 8. Gateway driving loop (uniform for all bots — never changes per bot)

```python
async def run_turn(bot_id, request):
    cfg = registry.get(bot_id)
    ctx = build_runtime_context(cfg, request)     # validates auth, builds Identity
    graph = registry.graph_for(bot_id)
    state_or_resume = normalize_input(request)    # §5
    async for event in graph.astream(
        state_or_resume,
        config={"configurable": {"ctx": ctx}, "thread_id": ctx.session_id},
        stream_mode=["messages", "custom", "updates"],
    ):
        yield translate(event)                    # -> protocol events
    # interrupt pending -> quick_replies/form + done:awaiting_input
    # else -> done:complete
```

`messages`→`text`; `custom`→`status`; `updates`→detect `__interrupt__`.

## 9. What a bot author writes

Exactly: (1) config file, (2) graph fragment (the middle region), (3) MCP server if
needed. NOT: session handling, auth, SSE, event translation, interrupt correlation,
checkpointer, guard/decline scaffolding.

Free-text fragment:
```python
def build(cfg, tools):
    def flow(g):
        g.add_node("agent", make_react_agent(cfg, tools))
        g.set_entry_after_guard("agent")
        g.add_edge("agent", END)
    return GraphFragment(flow)
```

Menu fragment:
```python
def build(cfg, tools):
    def flow(g):
        def menu(state, *, ctx):
            reply = ask_quick_replies("What do you need?",
                [{"id":"credits","label":"Check credits"},
                 {"id":"deadlines","label":"Deadlines"}], allow_free_text=True)
            choice = resolve_choice(reply, valid_ids={"credits","deadlines"})
            return {"scratch": {"route": choice}}
        g.add_node("menu", menu)
        g.add_node("credits", make_credits_node(cfg, tools))
        g.add_node("deadlines", make_deadlines_node(cfg))
        g.add_conditional_edges("menu", lambda s: s["scratch"]["route"],
                                {"credits":"credits","deadlines":"deadlines"})
        g.add_edge("credits", END); g.add_edge("deadlines", END)
    return GraphFragment(flow)
```

## 10. Conformance checklist (enforced by harness — see docs/06 §T7)

1. Operates only on `BotState` (no extra reserved top-level keys).
2. Reads identity/config only from `ctx` (no `state["identity"]`).
3. Emits status via `emit_status`, text via model node, interrupts via helpers only.
4. All MCP calls go through the identity-injecting wrapper.
5. Every interrupt node handles a clicked choice, and a typed reply when `allow_free_text` is true (`resolve_choice`).
6. Reaches `END` on every path.
7. Never touches checkpointer/session_id/SSE.
