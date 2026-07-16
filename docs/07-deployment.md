# 07 — Deployment

Single-tenant, replicated (docs/00 §Tenancy): one deployment per tenant. vLLM, the MCP
servers, and Keycloak run **elsewhere** — they are URLs in config, not services we run.

## Topology (three containers)

```
Browser (host page embeds <script src=".../widget.js" data-bot-id=…>)
   │  loads widget.js ───────────────►  widget   (static: nginx serving dist/)
   │  /config, /chat  ──► Caddy (TLS) ─┬─ /api/*  → gateway:8000   (SSE, streamed)
   │                                   └─ else    → widget:80
   ▼
 gateway ──► vLLM         (external, model_providers.base_url)
         ──► MCP servers  (external, mcp_servers.url)
         ──► Keycloak     (external, auth.jwks_url)
```

- **gateway** — FastAPI SSE gateway. Config mounted at `/config` (not baked → restart to
  reload). Secrets via env. Boots only if config validates (golden rule 4).
- **widget** — serves the single built `widget.js` (+ a production standalone page).
  Decoupled so it can be replaced by a self-hosted S3/object store (see below) with no
  gateway change.
- **caddy** — reverse proxy + automatic TLS. Routes `/api/*` to the gateway (with
  `flush_interval -1` so SSE tokens stream un-buffered) and everything else to the widget.

`docker compose up --build` runs all three. Set `SITE_ADDRESS` to a hostname in
production so Caddy provisions TLS via ACME; leave it `:80` for local HTTP.

Health: the gateway exposes `GET /healthz` (internal — no auth/origin gate). The compose
healthcheck hits it inside the container; it is not routed publicly by Caddy.

## Widget delivery

**Deploy the widget once; every site references it by URL.** It is a single
self-contained `widget.js` (Shadow DOM, no external deps). An embedding page adds:

```html
<script src="https://assistant.uni-osnabrueck.de/widget.js"
        data-bot-id="course-catalog"></script>
```

The script builds the UI in a Shadow root and fetches per-bot presentation (`/config`)
and chat (`/chat`) from the gateway. The **same** `widget.js` serves every bot and every
site; re-skinning is runtime (theme tokens from `/config`), not a per-site build.

Each embedding site needs two things:
1. the `<script>` tag (bot id; `data-base-url` only if the gateway is on a different
   origin than the script; optional `data-mode`, `data-scheme`, `data-get-token`);
2. its origin added to that bot's `embedding.allowed_origins` in config — this is the
   real gate (the gateway's Origin/CORS check). Loading the `.js` cross-origin is
   unrestricted; the gateway calls are what's gated.

Pages served from the **deployment's own host** (the standalone page, a demo page
behind the same Caddy) do NOT need allowlisting: the gateway treats an `Origin`
whose host matches the request `Host` as same-origin. Only third-party embedding
sites go in `allowed_origins`.

### Hosting options

- **Dedicated static container** (this compose): nginx serving `dist/`. Simple, immutable
  per image tag.
- **Self-hosted S3-compatible store (MinIO / Ceph RGW) — recommended target.** Drop the
  `widget` container; Caddy then only proxies `/api/*`. Publish the build to a **versioned
  prefix** and point pages at it:
  - upload `dist/widget.js` to e.g. `s3://widget/1.4.2/widget.js` (CI step: `mc cp` /
    `aws s3 cp`), keep a short-TTL `latest/` alias if you want rolling updates;
  - **serve over HTTPS** (front MinIO/Ceph with TLS, or your CDN) — an `https` page cannot
    load an `http` script (mixed content);
  - set **`Content-Type: application/javascript`** and long, immutable `Cache-Control` on
    versioned objects;
  - **no CORS headers needed** for a `<script src>` — only if you later add Subresource
    Integrity with `crossorigin`. The widget's own `fetch()`es target the gateway, so the
    object store's CORS is irrelevant to the app.

  Migrating container → S3 is just changing the `<script src>` URL; no gateway or config
  change.

## Config example — pointing at external services

Edit `config/global.yaml`. Only `*_env` fields are secrets (resolved from env); URLs are
plain config.

```yaml
model_providers:
  default:
    base_url: "https://vllm.svc.uni-osnabrueck.de/v1"   # your external vLLM
    api_key_env: "VLLM_API_KEY"                          # value in .env, never here
    default_model: "llama-3.3-70b-instruct"
  fast-small:
    base_url: "https://vllm-small.svc.uni-osnabrueck.de/v1"
    api_key_env: "VLLM_SMALL_API_KEY"

mcp_servers:
  course-catalog:
    transport: "streamable-http"
    url: "https://mcp-course-catalog.svc.uni-osnabrueck.de/mcp"   # your external MCP
    timeout_s: 20

auth:
  issuer:   "https://sso.uni-osnabrueck.de/realms/university"
  jwks_url: "https://sso.uni-osnabrueck.de/realms/university/protocol/openid-connect/certs"
  audience: "chatbots"
  leeway_s: 30
```

Secrets live in `.env` (see `.env.example`), mounted into the gateway via `env_file`.
`validate-config` fails boot if any referenced `*_env` var is unset (check 3).

## Secrets

- Config holds only references (`api_key_env`, `jwks_url`); values come from env.
- `.env` is git-ignored; commit `.env.example` only.
- The gateway image bakes no config and no secrets.

## Not covered here (arrives with Step 4c / real bots)

The example ships the `echo` stub bot. Real bots (course-catalog, enrollment, …) add a
config file + graph fragment + point `mcp_servers`/`model_providers` at the live services
above. The MCP servers themselves are separate deployments that enforce own-data-only
authorization server-side (docs/04 §7).
