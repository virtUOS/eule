"""Health probe used by container + reverse-proxy healthchecks."""

from __future__ import annotations


async def test_healthz_ok(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "echo" in body["bots"]
