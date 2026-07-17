"""T9 — Embedding & abuse (docs/06 §T9): origin gate, CORS preflight, rate limiting.

T9.3 (per-session token/cost cap) needs model token accounting and lands with the
model integration; T9.1/2/4 are gateway-level and covered here.
"""

from __future__ import annotations

import httpx
import pytest

from app.graphs.factory import GraphCache
from app.main import create_app
from app.registry.registry import Registry
from app.runtime.ratelimit import RateLimiter as RL
from app.runtime.sessions import Sessions

from .conftest import FakeClock, make_bot, make_global
from .test_protocol_t1 import collect

ALLOWED = "https://www.uni-osnabrueck.de"
CHAT = "/api/v1/bots/echo/chat"


# --- T9.1 — Origin gate on /chat -------------------------------------------

async def test_t9_1_disallowed_origin_forbidden(client):
    resp = await client.post(CHAT, json={"message": "hi"}, headers={"origin": "https://evil.example"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden_origin"


async def test_t9_1_allowed_origin_streams_with_cors(client):
    async with client.stream("POST", CHAT, json={"message": "hi"}, headers={"origin": ALLOWED}) as r:
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == ALLOWED
        assert "origin" in r.headers.get("vary", "").lower()
        await r.aread()


async def test_t9_1_no_origin_is_allowed(client):
    # same-origin / non-browser clients send no Origin → not gated
    events, _ = await collect(client, "echo", {"message": "hi"})
    assert events[-1]["data"]["status"] == "complete"


# --- T9.4 — CORS preflight (OPTIONS) ---------------------------------------

async def test_t9_4_preflight_allowed_origin(client):
    resp = await client.options(CHAT, headers={"origin": ALLOWED})
    assert resp.status_code == 204
    assert resp.headers["access-control-allow-origin"] == ALLOWED
    assert "POST" in resp.headers["access-control-allow-methods"]
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


async def test_t9_4_preflight_disallowed_origin_has_no_acao(client):
    resp = await client.options(CHAT, headers={"origin": "https://evil.example"})
    assert resp.status_code == 204
    assert "access-control-allow-origin" not in resp.headers


# --- T9.2 — Rate limiting ---------------------------------------------------

@pytest.fixture
def rated(fake_clock: FakeClock):
    gcfg = make_global()
    bot = make_bot(
        id="echo",  # reuse the echo graph via GraphCache
        rate_limit={"anonymous": {"requests_per_min": 2}},
    )
    registry = Registry(gcfg, {"echo": bot})
    sessions = Sessions(clock=fake_clock)
    app = create_app(
        registry, sessions=sessions, graphs=GraphCache(registry, sessions),
        ratelimiter=RL(clock=fake_clock),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_t9_2_rate_limit_429_with_retry_after(rated):
    async with rated as client:
        for _ in range(2):
            r = await client.post(CHAT, json={"message": "hi"})
            assert r.status_code == 200
            await r.aread()
        blocked = await client.post(CHAT, json={"message": "hi"})
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["code"] == "rate_limited"
        assert body["recoverable"] is True
        assert isinstance(body["retry_after"], int) and body["retry_after"] > 0


async def test_t9_2_window_resets(rated, fake_clock: FakeClock):
    async with rated as client:
        for _ in range(2):
            await (await client.post(CHAT, json={"message": "hi"})).aread()
        assert (await client.post(CHAT, json={"message": "hi"})).status_code == 429
        fake_clock.advance(61)  # next minute window
        ok = await client.post(CHAT, json={"message": "hi"})
        assert ok.status_code == 200
        await ok.aread()


# --- T9.2b — X-Forwarded-For trust policy (review batch 3) ------------------

def _one_per_min_app(fake_clock: FakeClock, *, trust_xff: bool):
    gcfg = make_global(**({"network": {"trust_forwarded_for": True}} if trust_xff else {}))
    bot = make_bot(id="echo", rate_limit={"anonymous": {"requests_per_min": 1}})
    registry = Registry(gcfg, {"echo": bot})
    sessions = Sessions(clock=fake_clock)
    app = create_app(
        registry, sessions=sessions, graphs=GraphCache(registry, sessions),
        ratelimiter=RL(clock=fake_clock),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_t9_2b_forged_xff_ignored_without_trusted_proxy(fake_clock):
    """Default (no trusted proxy): X-Forwarded-For is client-forgeable and must not
    mint fresh rate-limit buckets — rotating fake IPs must NOT bypass the limit."""
    async with _one_per_min_app(fake_clock, trust_xff=False) as client:
        r1 = await client.post(CHAT, json={"message": "hi"}, headers={"x-forwarded-for": "1.1.1.1"})
        assert r1.status_code == 200
        await r1.aread()
        r2 = await client.post(CHAT, json={"message": "hi"}, headers={"x-forwarded-for": "2.2.2.2"})
        assert r2.status_code == 429  # same real peer → same bucket, spoof ignored


async def test_t9_2b_rightmost_hop_used_behind_trusted_proxy(fake_clock):
    """Behind a trusted proxy the RIGHTMOST entry (appended by OUR proxy) keys the
    bucket; the client-authored leftmost entries are ignored — so an attacker can
    neither escape their own bucket nor exhaust a victim's."""
    async with _one_per_min_app(fake_clock, trust_xff=True) as client:
        r1 = await client.post(
            CHAT, json={"message": "hi"}, headers={"x-forwarded-for": "9.9.9.9, 1.1.1.1"}
        )
        assert r1.status_code == 200
        await r1.aread()
        # same real client, different forged leftmost → SAME bucket → limited
        r2 = await client.post(
            CHAT, json={"message": "hi"}, headers={"x-forwarded-for": "8.8.8.8, 1.1.1.1"}
        )
        assert r2.status_code == 429
        # a different real client gets its own bucket
        r3 = await client.post(
            CHAT, json={"message": "hi"}, headers={"x-forwarded-for": "9.9.9.9, 2.2.2.2"}
        )
        assert r3.status_code == 200
        await r3.aread()


def test_ratelimiter_sweep_drops_expired_windows(fake_clock):
    rl = RL(clock=fake_clock)
    rl.check("a", per_min=10, per_day=None)
    rl.check("b", per_min=10, per_day=100)  # day window outlives the minute one
    fake_clock.advance(61)
    swept = rl.sweep()
    assert swept == 2  # both minute windows expired ('a' min + 'b' min)
    rl.check("a", per_min=10, per_day=None)  # still functional after GC


# --- T9.1b — true same-origin needs no allowlisting (review batch 4) ---------

async def test_t9_1b_same_origin_allowed_without_allowlist(client):
    """Browsers send Origin on EVERY POST including same-origin ones. The
    deployment's own pages (standalone page, demo host) must not 403 on /chat just
    because their own origin isn't in the embed allowlist."""
    # ASGI test host is "test"; an Origin on the same host is true same-origin.
    async with client.stream(
        "POST", CHAT, json={"message": "hi"}, headers={"origin": "http://test", "host": "test"}
    ) as r:
        assert r.status_code == 200
        # same-origin: no CORS headers needed (nothing for the browser to check)
        assert "access-control-allow-origin" not in r.headers
        await r.aread()


async def test_t9_1b_cross_origin_still_gated(client):
    resp = await client.post(
        CHAT, json={"message": "hi"},
        headers={"origin": "https://evil.example", "host": "test"},
    )
    assert resp.status_code == 403


# --- T9.1c — dev_allow_localhost (review follow-up) --------------------------

def _localhost_app(*, dev_allow: bool):
    gcfg = make_global(**({"network": {"dev_allow_localhost": True}} if dev_allow else {}))
    # allowlist a production origin only; localhost is NOT listed
    bot = make_bot(id="echo", embedding={"mode": "launcher", "allowed_origins": [ALLOWED]})
    registry = Registry(gcfg, {"echo": bot})
    sessions = Sessions(clock=FakeClock())
    app = create_app(registry, sessions=sessions, graphs=GraphCache(registry, sessions))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_t9_1c_localhost_forbidden_by_default():
    async with _localhost_app(dev_allow=False) as client:
        resp = await client.post(CHAT, json={"message": "hi"}, headers={"origin": "http://localhost:5173"})
        assert resp.status_code == 403 and resp.json()["code"] == "forbidden_origin"


async def test_t9_1c_localhost_allowed_when_dev_flag_set():
    async with _localhost_app(dev_allow=True) as client:
        # any port + 127.0.0.1 + preflight all pass, and the specific origin is echoed
        for origin in ("http://localhost:5173", "http://localhost:9999", "http://127.0.0.1:3000"):
            async with client.stream("POST", CHAT, json={"message": "hi"}, headers={"origin": origin}) as r:
                assert r.status_code == 200, origin
                assert r.headers["access-control-allow-origin"] == origin
                await r.aread()
        pre = await client.options(CHAT, headers={"origin": "http://localhost:5173"})
        assert pre.status_code == 204
        assert pre.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_t9_1c_dev_flag_does_not_open_non_localhost():
    async with _localhost_app(dev_allow=True) as client:
        resp = await client.post(CHAT, json={"message": "hi"}, headers={"origin": "https://evil.example"})
        assert resp.status_code == 403  # only loopback is relaxed, nothing else
