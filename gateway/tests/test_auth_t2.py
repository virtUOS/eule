"""T2 — Auth path (docs/06 §T2). RSA-signed JWTs verified via an injected key,
so no real Keycloak/JWKS network access is needed."""

from __future__ import annotations

import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from app.auth.keycloak import AuthVerifier
from app.graphs.emit import ask_quick_replies, emit_status
from app.graphs.skeleton import BotGraphBuilder, BotState, GraphFragment, build_bot_graph
from app.main import create_app
from app.registry.models import AuthCfg
from app.registry.registry import Registry

from .conftest import make_bot, make_global
from .test_protocol_t1 import collect

# One keypair for the whole module; the verifier resolves to the public key directly.
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC = _PRIVATE.public_key()

AUTH = {
    "issuer": "https://sso.test/realms/uni",
    "jwks_url": "https://sso.test/realms/uni/protocol/openid-connect/certs",
    "audience": "chatbots",
    "leeway_s": 30,
}


def make_token(sub: str = "user-x", roles: tuple[str, ...] = ("student",), exp_delta: int = 3600, **over: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": AUTH["issuer"],
        "aud": AUTH["audience"],
        "sub": sub,
        "iat": now,
        "exp": now + exp_delta,
        "realm_access": {"roles": list(roles)},
    }
    claims.update(over)
    return jwt.encode(claims, _PRIVATE, algorithm="RS256")


class _StubGraphs:
    def __init__(self, graph: object) -> None:
        self._graph = graph

    def get(self, _bot_id: str) -> object:
        return self._graph


def _probe_fragment() -> GraphFragment:
    """Emits the ctx subject via an ephemeral status event (proves identity reached the
    node) WITHOUT ever writing it into BotState/checkpoint."""

    def flow(b: BotGraphBuilder) -> None:
        async def probe(state: BotState, config: RunnableConfig) -> dict:
            ctx = config["configurable"]["ctx"]
            emit_status("thinking", f"subject={ctx.identity.subject}")
            return {"scratch": {}}

        b.add_node("probe", probe)
        b.set_entry_after_guard("probe")
        b.add_edge("probe", END)

    return GraphFragment(flow)


def _menu_fragment() -> GraphFragment:
    def flow(b: BotGraphBuilder) -> None:
        async def menu(state: BotState, config: RunnableConfig) -> dict:
            reply = ask_quick_replies("Pick", [{"id": "a", "label": "A"}], allow_free_text=False)
            return {"scratch": {"picked": reply.get("id")}}

        b.add_node("menu", menu)
        b.set_entry_after_guard("menu")
        b.add_edge("menu", END)

    return GraphFragment(flow)


def _build(fragment: GraphFragment, sessions):
    gcfg = make_global(auth=AUTH)
    bot = make_bot(
        id="secure", requires_auth=True,
        identity={"subject_claim": "sub", "required_roles": ["student"]},
    )
    registry = Registry(gcfg, {"secure": bot})
    graph = build_bot_graph(bot, [], fragment, sessions.checkpointer)
    verifier = AuthVerifier(AuthCfg(**AUTH), key_resolver=lambda _t: _PUBLIC)
    app = create_app(registry, sessions=sessions, graphs=_StubGraphs(graph), auth=verifier)
    return app


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# T2.1 — missing token → 401, no graph exec (no stream)
async def test_t2_1_missing_token(sessions):
    async with _client(_build(_probe_fragment(), sessions)) as client:
        resp = await client.post("/api/v1/bots/secure/chat", json={"message": "hi"})
        assert resp.status_code == 401
        assert resp.json()["code"] == "unauthorized"
        assert resp.headers["content-type"].startswith("application/json")  # not a stream


# T2.2 — expired token → token_expired (recoverable)
async def test_t2_2_expired_token(sessions):
    async with _client(_build(_probe_fragment(), sessions)) as client:
        tok = make_token(exp_delta=-3600)  # expired an hour ago (beyond leeway)
        resp = await client.post(
            "/api/v1/bots/secure/chat", json={"message": "hi"},
            headers={"authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == "token_expired"
        assert body["recoverable"] is True


# T2.3 — valid token → identity.subject in ctx, ABSENT from checkpoint
async def test_t2_3_identity_in_ctx_not_in_checkpoint(sessions):
    app = _build(_probe_fragment(), sessions)
    async with _client(app) as client:
        tok = make_token(sub="user-x")
        events, _ = await collect(
            client, "secure", {"message": "hi"}, headers={"authorization": f"Bearer {tok}"}
        )
        # ctx carried the trusted subject into the node (ephemeral status event)
        statuses = [e["data"]["label"] for e in events if e["data"]["type"] == "status"]
        assert "subject=user-x" in statuses
        assert events[-1]["data"]["status"] == "complete"
        sid = events[0]["data"]["session_id"]

    # inspect the persisted checkpoint: the subject must NOT appear anywhere in it
    ckpt = sessions.checkpointer.get_tuple({"configurable": {"thread_id": sid}})
    assert ckpt is not None
    assert "user-x" not in str(ckpt.checkpoint)


# T2.4 — missing role → forbidden (403)
async def test_t2_4_missing_role_forbidden(sessions):
    async with _client(_build(_probe_fragment(), sessions)) as client:
        tok = make_token(roles=("staff",))  # bot requires "student"
        resp = await client.post(
            "/api/v1/bots/secure/chat", json={"message": "hi"},
            headers={"authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "forbidden"


# SEC#2 — a session is bound to its owner; another authenticated user cannot continue it
async def test_sec_session_bound_to_subject(sessions):
    app = _build(_probe_fragment(), sessions)
    async with _client(app) as client:
        tok_a = make_token(sub="user-a")
        ev_a, _ = await collect(
            client, "secure", {"message": "hi"}, headers={"authorization": f"Bearer {tok_a}"}
        )
        assert ev_a[-1]["data"]["status"] == "complete"
        sid = ev_a[0]["data"]["session_id"]

        # a DIFFERENT authenticated user must not be able to continue user-a's session
        tok_b = make_token(sub="user-b")
        ev_b, _ = await collect(
            client, "secure", {"session_id": sid, "message": "whose session?"},
            headers={"authorization": f"Bearer {tok_b}"},
        )
        assert "session_not_found" in [e["data"].get("code") for e in ev_b]

        # the owner can still continue it
        ev_a2, _ = await collect(
            client, "secure", {"session_id": sid, "message": "still me"},
            headers={"authorization": f"Bearer {tok_a}"},
        )
        assert ev_a2[-1]["data"]["status"] == "complete"


# T2.5 — token expiry between interrupt and resume → token_expired on resume,
#          session survives, retry after refresh works
async def test_t2_5_expiry_between_interrupt_and_resume(sessions):
    app = _build(_menu_fragment(), sessions)
    async with _client(app) as client:
        good = make_token()
        ev1, _ = await collect(
            client, "secure", {"message": "go"}, headers={"authorization": f"Bearer {good}"}
        )
        qr = next(e["data"] for e in ev1 if e["data"]["type"] == "quick_replies")
        sid = ev1[0]["data"]["session_id"]

        # resume with an EXPIRED token → 401 token_expired, pre-stream; session untouched
        expired = make_token(exp_delta=-3600)
        resp = await client.post(
            "/api/v1/bots/secure/chat",
            json={"session_id": sid, "choice": {"id": "a"}, "reply_to": qr["reply_to"]},
            headers={"authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "token_expired"

        # retry after refresh (fresh token) → the interrupt still resumes
        fresh = make_token()
        ev2, _ = await collect(
            client, "secure",
            {"session_id": sid, "choice": {"id": "a"}, "reply_to": qr["reply_to"]},
            headers={"authorization": f"Bearer {fresh}"},
        )
        assert ev2[-1]["data"]["status"] == "complete"
