"""Config loading: parse YAML, deep-merge the overridable subset with global
`defaults`, construct typed models. Cross-cutting validation lives in `validation.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from .models import BotCfg, Defaults, GlobalCfg
from .registry import Registry
from .validation import check_all

OVERRIDABLE_KEYS = (
    "session_ttl_s",
    "max_message_chars",
    "history_max_turns",
    "rate_limit",
    "guard",
    "greeting",
)


def deep_merge(base: Any, override: Any) -> Any:
    """Generic deep-merge: override wins; nested dicts merged key-by-key (so
    rate-limit tiers merge independently); `None` override keeps base."""
    if override is None:
        return base
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(out.get(k), v)
        return out
    return override


def _resolve_overridable(defaults: Defaults, raw: dict[str, Any]) -> dict[str, Any]:
    defaults_dump = defaults.model_dump()
    eff = dict(raw)
    for key in OVERRIDABLE_KEYS:
        eff[key] = deep_merge(defaults_dump.get(key), raw.get(key))
    return eff


class LoadResult:
    def __init__(
        self,
        registry: Registry | None,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        self.registry = registry
        self.errors = errors
        self.warnings = warnings

    @property
    def ok(self) -> bool:
        return self.registry is not None and not self.errors


def _fmt_validation_error(source: str, exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{source}: {loc}: {err['msg']}")
    return out


def load_and_validate(
    config_dir: str | Path,
    env: Mapping[str, str] | None = None,
) -> LoadResult:
    """Load + validate config WITHOUT booting. Collects all errors across files."""
    env = os.environ if env is None else env
    config_dir = Path(config_dir)
    errors: list[str] = []
    warnings: list[str] = []

    # global.yaml
    gcfg: GlobalCfg | None = None
    gpath = config_dir / "global.yaml"
    if not gpath.exists():
        errors.append(f"{gpath}: missing global.yaml")
    else:
        try:
            gcfg = GlobalCfg(**(yaml.safe_load(gpath.read_text()) or {}))
        except ValidationError as e:
            errors.extend(_fmt_validation_error("global.yaml", e))

    # bots/*.yaml
    defaults = gcfg.defaults if gcfg else Defaults()
    parsed: list[tuple[str, BotCfg]] = []
    seen_ids: dict[str, str] = {}
    bots_dir = config_dir / "bots"
    for path in sorted(bots_dir.glob("*.yaml")) if bots_dir.exists() else []:
        raw = yaml.safe_load(path.read_text()) or {}
        try:
            bot = BotCfg(**_resolve_overridable(defaults, raw))
        except ValidationError as e:
            errors.extend(_fmt_validation_error(path.name, e))
            continue
        # lint: filename stem == id (docs/03 §Layout)
        if bot.id != path.stem:
            errors.append(f"{path.name}: filename stem != id ({bot.id!r})")
        if bot.id in seen_ids:
            errors.append(
                f"{path.name}: duplicate bot id {bot.id!r} (also in {seen_ids[bot.id]})"
            )
        else:
            seen_ids[bot.id] = path.name
        parsed.append((path.name, bot))

    bots = {b.id: b for _, b in parsed}

    if gcfg is not None:
        e2, w2 = check_all(gcfg, bots, env)
        errors.extend(e2)
        warnings.extend(w2)

    registry = Registry(gcfg, bots) if gcfg is not None and not errors else None
    return LoadResult(registry, errors, warnings)
