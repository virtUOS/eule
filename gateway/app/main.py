"""FastAPI app factory + wiring (BUILD_PLAN Step 1).

`create_app` takes an already-loaded registry so tests inject fixtures. The module-level
`app` boots from `CONFIG_DIR` (default `../config`) and fails fast on invalid config
(golden rule 4) — this is what `uvicorn app.main:app` runs.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI

from .api import native
from .auth.keycloak import build_verifier
from .graphs.factory import GraphCache
from .registry.loader import load_and_validate
from .registry.registry import Registry
from .runtime.ratelimit import RateLimiter
from .runtime.sessions import Sessions

SWEEP_INTERVAL_S = 60.0


async def _sweep_loop(sessions: Sessions, ratelimiter: RateLimiter, interval_s: float) -> None:
    """Periodic GC: expired sessions (incl. their checkpointer threads) and expired
    rate-limit windows. Without this, both stores grow unboundedly — sessions are
    minted per request-with-bad-id and limiter keys are client-mintable (per-IP)."""
    while True:
        await asyncio.sleep(interval_s)
        sessions.sweep()
        ratelimiter.sweep()


def create_app(
    registry: Registry,
    sessions: Sessions | None = None,
    graphs: Any = None,
    auth: Any = None,
    ratelimiter: RateLimiter | None = None,
) -> FastAPI:
    sessions = sessions or Sessions()
    graphs = graphs or GraphCache(registry, sessions)
    limiter = ratelimiter or RateLimiter()

    # Prewarm: build every enabled bot's compiled graph NOW, so fragment-level config
    # errors (e.g. a required tool missing from the allowlist, a provider without a
    # default_model) fail at boot — golden rule 4 — instead of 500ing on the bot's
    # first request. No network happens at build time (clients are constructed lazy).
    for bot_id in registry.ids():
        if registry.get(bot_id).enabled:
            graphs.get(bot_id)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_sweep_loop(sessions, limiter, SWEEP_INTERVAL_S))
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Scoped AI Support Bots — Gateway", lifespan=lifespan)
    app.state.registry = registry
    app.state.sessions = sessions
    app.state.graphs = graphs
    app.state.ratelimiter = limiter
    # Verifier for requires_auth bots; None when the deployment has no auth block.
    app.state.auth = auth if auth is not None else build_verifier(registry.global_cfg.auth)
    app.include_router(native.router)
    return app


def build_default_app() -> FastAPI:
    config_dir = os.environ.get("CONFIG_DIR", str(Path(__file__).resolve().parents[2] / "config"))
    result = load_and_validate(config_dir)
    for w in result.warnings:
        print(f"config WARN: {w}")
    if not result.ok or result.registry is None:
        for e in result.errors:
            print(f"config ERROR: {e}")
        raise SystemExit(f"Refusing to boot: invalid config in {config_dir}")
    return create_app(result.registry)


# Lazy module-level `app` so importing helpers (create_app) for tests does NOT boot
# from disk. `uvicorn app.main:app` triggers the build here and fails fast on bad config.
def __getattr__(name: str) -> FastAPI:
    if name == "app":
        return build_default_app()
    raise AttributeError(name)
