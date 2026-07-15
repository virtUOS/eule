"""Startup validation — checks 1–13 (docs/03 §Validation). Fail boot on any error.

Checks 10–12 concern routers (`routes` block); they are no-ops for non-router bots
and are ready for Step 5b. Check 8 (override shape) is enforced structurally by the
shared Pydantic models, so there is no runtime check here.
"""

from __future__ import annotations

import re
from typing import Mapping

from pydantic import ValidationError

from ..graphs.registry import FRAGMENT_PARAM_MODELS, known_graphs
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

    # 3. Every `*_env` reference resolves (model-provider api keys + MCP bearer tokens).
    for name, prov in gcfg.model_providers.items():
        if prov.api_key_env not in env:
            errors.append(
                f"check 3: model_providers.{name}.api_key_env '{prov.api_key_env}' "
                f"is not set in the environment"
            )
    for name, mcp_cfg in gcfg.mcp_servers.items():
        if mcp_cfg.bearer_token_env is not None and mcp_cfg.bearer_token_env not in env:
            errors.append(
                f"check 3: mcp_servers.{name}.bearer_token_env '{mcp_cfg.bearer_token_env}' "
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

        # 13. graph resolves to a registered fragment builder (fail boot, not first request).
        if bot.graph not in known_graphs():
            errors.append(
                f"check 13: {where}: graph '{bot.graph}' is not registered "
                f"(known: {', '.join(known_graphs())})"
            )

        # 14. graph_params validate against the selected fragment's params model
        # (docs/03 §graph_params); stock-fragment invariants hold. Skipped when the
        # graph is unknown — check 13 already reported it.
        elif (params_model := FRAGMENT_PARAM_MODELS.get(bot.graph)) is not None:
            try:
                params = params_model(**bot.graph_params)
            except ValidationError as e:
                for err in e.errors():
                    loc = ".".join(str(p) for p in err["loc"]) or "(root)"
                    errors.append(
                        f"check 14: {where}: graph_params.{loc}: {err['msg']} "
                        f"(graph '{bot.graph}')"
                    )
            else:
                effective = set(bot.tools.allow) - set(bot.tools.deny)
                sources_from = getattr(params, "sources_from", None)
                if sources_from:
                    for tool in sources_from:
                        if tool not in effective:
                            errors.append(
                                f"check 14: {where}: graph_params.sources_from: "
                                f"'{tool}' is not in the effective tool allowlist"
                            )
                if bot.graph == "tool-agent" and not effective:
                    errors.append(
                        f"check 14: {where}: graph 'tool-agent' requires a non-empty "
                        f"effective tool allowlist (allow minus deny)"
                    )
                # router ⇔ routes consistency (BUILD_PLAN 9c): the stock router needs
                # targets; a routes block on any other graph would be silently dead.
                if bot.graph == "router" and (bot.routes is None or not bot.routes.targets):
                    errors.append(
                        f"check 14: {where}: graph 'router' requires a routes block "
                        f"with at least one target"
                    )
                if bot.routes is not None and bot.graph != "router":
                    errors.append(
                        f"check 14: {where}: routes block present but graph is "
                        f"'{bot.graph}' (an orchestrator must use graph 'router')"
                    )

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
                if target.routes is not None:
                    errors.append(
                        f"check 10: {where}: routes target '{tgt.bot}' is itself a "
                        f"router (nested routers unsupported in v1)"
                    )
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
