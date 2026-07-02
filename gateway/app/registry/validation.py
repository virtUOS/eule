"""Startup validation — checks 1–12 (docs/03 §Validation). Fail boot on any error.

Checks 10–12 concern routers (`routes` block); they are no-ops for non-router bots
and are ready for Step 5b. Check 8 (override shape) is enforced structurally by the
shared Pydantic models, so there is no runtime check here.
"""

from __future__ import annotations

import re
from typing import Mapping

from .models import BotCfg, GlobalCfg
from .theme import contrast_violations, resolve_theme

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def check_all(
    gcfg: GlobalCfg,
    bots: Mapping[str, BotCfg],
    env: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # 3. Every `*_env` reference resolves (global model-provider api keys).
    for name, prov in gcfg.model_providers.items():
        if prov.api_key_env not in env:
            errors.append(
                f"check 3: model_providers.{name}.api_key_env '{prov.api_key_env}' "
                f"is not set in the environment"
            )

    for bot in bots.values():
        where = f"bot '{bot.id}'"

        # 1. model.provider exists.
        if bot.model.provider not in gcfg.model_providers:
            errors.append(f"check 1: {where}: model.provider '{bot.model.provider}' unknown")

        # 2. tools.mcp_servers entries exist.
        for srv in bot.tools.mcp_servers:
            if srv not in gcfg.mcp_servers:
                errors.append(f"check 2: {where}: mcp_server '{srv}' not in global.mcp_servers")

        # 4. id regex (uniqueness handled in loader).
        if not _ID_RE.match(bot.id):
            errors.append(f"check 4: {where}: id does not match {_ID_RE.pattern}")

        # 5. requires_auth ⇒ identity present ⇒ global auth present.
        if bot.requires_auth:
            if bot.identity is None:
                errors.append(f"check 5: {where}: requires_auth but no identity block")
            if gcfg.auth is None:
                errors.append(f"check 5: {where}: requires_auth but global auth is absent")

        # 6. guard.enabled ⇒ guard.provider resolves.
        if bot.guard.enabled:
            if bot.guard.provider is None:
                errors.append(f"check 6: {where}: guard.enabled but no guard.provider")
            elif bot.guard.provider not in gcfg.model_providers:
                errors.append(
                    f"check 6: {where}: guard.provider '{bot.guard.provider}' unknown"
                )

        # 7. WARN: public no-auth, non-router bot with guard disabled.
        if not bot.requires_auth and bot.routes is None and not bot.guard.enabled:
            warnings.append(
                f"check 7: {where}: public non-router bot has guard.enabled=false "
                f"(recommended on for public bots)"
            )

        # 9. Theme contrast against resolved tokens (per bot: deployment theme + override).
        resolved = resolve_theme(gcfg.theme, bot.theme)
        for v in contrast_violations(resolved):
            errors.append(f"check 9: {where}: {v}")

        # 10–12. Router checks.
        if bot.routes is not None:
            # 12. mode ∈ {menu} for v1.
            if bot.routes.mode != "menu":
                errors.append(
                    f"check 12: {where}: routes.mode '{bot.routes.mode}' unsupported "
                    f"(v1 allows only 'menu')"
                )
            for tgt in bot.routes.targets:
                # 10. target exists, enabled, not self.
                if tgt.bot == bot.id:
                    errors.append(f"check 10: {where}: routes target '{tgt.bot}' is the router itself")
                    continue
                target = bots.get(tgt.bot)
                if target is None:
                    errors.append(f"check 10: {where}: routes target '{tgt.bot}' does not exist")
                    continue
                if not target.enabled:
                    errors.append(f"check 10: {where}: routes target '{tgt.bot}' is not enabled")
                # 11. auth-posture invariant: target.requires_auth <= router.requires_auth.
                if target.requires_auth and not bot.requires_auth:
                    errors.append(
                        f"check 11: {where}: public router may not route to auth bot "
                        f"'{tgt.bot}'"
                    )

    # 9 (deployment theme itself, independent of any bot).
    for v in contrast_violations(resolve_theme(gcfg.theme)):
        errors.append(f"check 9: deployment theme: {v}")

    return errors, warnings
