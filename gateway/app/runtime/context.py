"""RuntimeContext + Identity (docs/04 §2).

Identity is injected here, out-of-band, and NEVER placed in BotState, a checkpoint, a
model-visible tool param, or the prompt (golden rule 2). There is no `surface` field
(the OpenAI surface was cut).

Step 1: auth is stubbed — Keycloak JWT validation lands in Step 3. For now every
request yields an anonymous Identity. The `requires_auth` enforcement point is here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..registry.models import BotCfg


@dataclass(frozen=True)
class Identity:
    authenticated: bool
    subject: str | None
    claims: dict[str, Any]
    roles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeContext:
    bot_id: str
    config: "BotCfg"
    identity: Identity
    session_id: str
    request_id: str
    locale: str | None


ANONYMOUS = Identity(authenticated=False, subject=None, claims={}, roles=[])


def build_runtime_context(
    cfg: "BotCfg",
    *,
    session_id: str,
    request_id: str,
    locale: str | None = None,
    identity: Identity = ANONYMOUS,
) -> RuntimeContext:
    # Identity is validated PRE-STREAM in the endpoint (Keycloak, docs/01 401/403) and
    # passed in here already-trusted. Public/no-auth bots get ANONYMOUS.
    return RuntimeContext(
        bot_id=cfg.id,
        config=cfg,
        identity=identity,
        session_id=session_id,
        request_id=request_id,
        locale=locale,
    )
