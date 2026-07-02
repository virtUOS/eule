"""T8 — Session & scaling (docs/06 §T8.1–2). TTL eviction and restart both surface
`session_not_found` so the widget can start fresh."""

from __future__ import annotations

from app.graphs.factory import GraphCache
from app.main import create_app
from app.runtime.sessions import Sessions

from .conftest import FakeClock
from .test_protocol_t1 import collect


# --- unit-level TTL behaviour ----------------------------------------------

def test_session_evicts_after_ttl():
    clock = FakeClock()
    s = Sessions(clock=clock, id_factory=lambda: "sid-1")
    sess = s.new("echo", ttl_s=1800)
    assert s.get("sid-1") is sess
    clock.advance(1799)
    assert s.get("sid-1") is not None
    clock.advance(2)  # now > expires_at
    assert s.get("sid-1") is None  # evicted
    assert s.count() == 0


def test_touch_extends_ttl():
    clock = FakeClock()
    s = Sessions(clock=clock, id_factory=lambda: "sid-1")
    sess = s.new("echo", ttl_s=100)
    clock.advance(90)
    s.touch(sess, 100)
    clock.advance(90)
    assert s.get("sid-1") is not None  # still alive thanks to touch


def test_sweep_removes_expired():
    clock = FakeClock()
    ids = iter(["a", "b"])
    s = Sessions(clock=clock, id_factory=lambda: next(ids))
    s.new("echo", ttl_s=10)
    s.new("echo", ttl_s=10)
    clock.advance(11)
    assert s.sweep() == 2
    assert s.count() == 0


# --- T8.1 — TTL eviction over the wire → session_not_found -----------------

async def test_t8_1_ttl_eviction_over_wire(client, fake_clock):
    first, _ = await collect(client, "echo", {"message": "hello"})
    sid = first[0]["data"]["session_id"]

    fake_clock.advance(1801)  # past session_ttl_s (1800)

    events, _ = await collect(client, "echo", {"session_id": sid, "message": "still there?"})
    codes = [e["data"].get("code") for e in events]
    assert "session_not_found" in codes
    assert events[-1]["data"]["status"] == "error"
    # a fresh session id is minted so the widget can start over
    new_sid = events[0]["data"]["session_id"]
    assert new_sid != sid


# --- T8.2 — restart drops sessions → session_not_found handled -------------

async def test_t8_2_restart_drops_sessions(registry):
    """A restart == a new in-memory store. An old session id is simply not found."""
    import httpx

    clock1 = FakeClock()
    s1 = Sessions(clock=clock1, id_factory=lambda: "old-session")
    app1 = create_app(registry, sessions=s1, graphs=GraphCache(registry, s1))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app1), base_url="http://test"
    ) as c1:
        first, _ = await collect(c1, "echo", {"message": "hello"})
        sid = first[0]["data"]["session_id"]
        assert sid == "old-session"

    # "restart": brand-new store/app, empty session table
    clock2 = FakeClock()
    s2 = Sessions(clock=clock2, id_factory=lambda: "new-session")
    app2 = create_app(registry, sessions=s2, graphs=GraphCache(registry, s2))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2), base_url="http://test"
    ) as c2:
        events, _ = await collect(c2, "echo", {"session_id": sid, "message": "resume?"})
        assert "session_not_found" in [e["data"].get("code") for e in events]
        assert events[-1]["data"]["status"] == "error"
