# 02 — Dual API Surface — REMOVED

The OpenAI-compatible adapter was cut. It was aspirational (no named consumer) and
imposed ongoing cost (every menu bot forced to support free-text equivalents, a
`surface` branch in the node contract, a config check validating a code property).

Two cheap structural hooks were KEPT because they're good design regardless:
1. **Bot ids are a stable identifier.**
2. **The gateway runs an internal event stream; the native SSE layer is a thin
   translator over it.** (Do not couple graph logic to the wire protocol.)

If a real third-party-frontend consumer ever appears, it is an *additive* translator
over that internal event stream. Do not pre-build it.