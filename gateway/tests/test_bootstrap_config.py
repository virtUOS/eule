"""GET /api/v1/bots/{id}/config — widget bootstrap (docs/01 §Widget bootstrap)."""

from __future__ import annotations

ALLOWED = "https://www.uni-osnabrueck.de"


async def test_bootstrap_returns_presentation_config(client):
    resp = await client.get("/api/v1/bots/echo/config?lang=en", headers={"origin": ALLOWED})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Echo Bot"
    assert set(body["theme"]) == {"light", "dark", "dark_mode", "radius"}
    assert body["theme"]["light"]["--primary"] == "#a6093d"
    assert body["greeting"]["mode"] == "client_initiated"
    assert body["starter_replies"][0]["query"] == "Hello!"
    # no secrets leak into the bootstrap payload
    assert "api_key" not in resp.text.lower()


async def test_bootstrap_unknown_bot_404(client):
    resp = await client.get("/api/v1/bots/ghost/config")
    assert resp.status_code == 404
    assert resp.json()["code"] == "unknown_bot"


async def test_bootstrap_forbidden_origin(client):
    resp = await client.get(
        "/api/v1/bots/echo/config", headers={"origin": "https://evil.example"}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden_origin"


async def test_bootstrap_etag_304(client):
    r1 = await client.get("/api/v1/bots/echo/config", headers={"origin": ALLOWED})
    etag = r1.headers["etag"]
    r2 = await client.get(
        "/api/v1/bots/echo/config",
        headers={"origin": ALLOWED, "if-none-match": etag},
    )
    assert r2.status_code == 304
