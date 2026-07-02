"""Keycloak OIDC bearer-token validation (BUILD_PLAN Step 3).

Validates a JWT against the realm JWKS (signature, issuer, audience, expiry+leeway),
extracts the trusted subject + roles, and enforces `required_roles`. The result is an
`Identity` that the gateway injects out-of-band via RuntimeContext — it is NEVER placed
in BotState, a checkpoint, the prompt, or a model-visible tool parameter (golden rule 2).

Token validation happens PRE-STREAM in the endpoint, so failures map to HTTP 401/403
with the protocol error shape (docs/01), before any graph runs.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

import jwt

from ..registry.models import AuthCfg, IdentityCfg
from ..runtime.context import Identity


class AuthError(Exception):
    """Auth failure mapped to a pre-stream protocol error (docs/01 error codes)."""

    def __init__(self, code: str, message: str, *, status: int, recoverable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.recoverable = recoverable

    @classmethod
    def unauthorized(cls, message: str = "Missing or invalid token.") -> "AuthError":
        return cls("unauthorized", message, status=401, recoverable=False)

    @classmethod
    def token_expired(cls, message: str = "Your session token has expired.") -> "AuthError":
        return cls("token_expired", message, status=401, recoverable=True)

    @classmethod
    def forbidden(cls, message: str = "You do not have the required role.") -> "AuthError":
        return cls("forbidden", message, status=403, recoverable=False)


class KeyResolver(Protocol):
    def __call__(self, token: str) -> Any: ...


def _extract_roles(claims: dict[str, Any]) -> list[str]:
    """Keycloak realm roles live under realm_access.roles."""
    realm = claims.get("realm_access")
    if isinstance(realm, dict):
        roles = realm.get("roles")
        if isinstance(roles, list):
            return [str(r) for r in roles]
    return []


class AuthVerifier:
    def __init__(self, auth_cfg: AuthCfg, key_resolver: KeyResolver | None = None) -> None:
        self._cfg = auth_cfg
        # A JWKS client is created lazily so construction never does network I/O.
        # Tests inject a key_resolver that returns a local public key.
        self._key_resolver = key_resolver
        self._jwks: Any = None

    def _resolve_key(self, token: str) -> Any:
        if self._key_resolver is not None:
            return self._key_resolver(token)
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self._cfg.jwks_url)
        return self._jwks.get_signing_key_from_jwt(token).key

    def verify(self, token: str, identity_cfg: IdentityCfg) -> Identity:
        try:
            key = self._resolve_key(token)
        except AuthError:
            raise
        except Exception as e:  # JWKS lookup / bad token header
            raise AuthError.unauthorized(f"Token key resolution failed: {e}") from e

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._cfg.audience,
                issuer=self._cfg.issuer,
                leeway=self._cfg.leeway_s,
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthError.token_expired() from e
        except jwt.InvalidTokenError as e:
            raise AuthError.unauthorized(f"Invalid token: {e}") from e

        subject = claims.get(identity_cfg.subject_claim)
        if not subject:
            raise AuthError.unauthorized(
                f"Token missing subject claim '{identity_cfg.subject_claim}'."
            )

        roles = _extract_roles(claims)
        missing = [r for r in identity_cfg.required_roles if r not in roles]
        if missing:
            raise AuthError.forbidden(f"Missing required role(s): {', '.join(missing)}.")

        return Identity(
            authenticated=True,
            subject=str(subject),
            claims=claims,
            roles=roles,
        )


def bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return parts[1].strip()
    return None


# A verifier factory usable by create_app; kept here so the wiring is testable.
def build_verifier(auth_cfg: AuthCfg | None) -> AuthVerifier | None:
    return AuthVerifier(auth_cfg) if auth_cfg is not None else None


VerifierFn = Callable[[str, IdentityCfg], Identity]
