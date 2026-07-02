"""`python -m app.cli validate-config config/` — run all checks without booting.
Exits non-zero on any error so it can gate CI (docs/03 §Validation, BUILD_PLAN Step 0)."""

from __future__ import annotations

import sys

from .registry.loader import load_and_validate


def validate_config(config_dir: str) -> int:
    result = load_and_validate(config_dir)
    for w in result.warnings:
        print(f"WARN  {w}")
    for e in result.errors:
        print(f"ERROR {e}")
    if result.errors:
        print(f"\nvalidate-config: FAILED ({len(result.errors)} error(s), "
              f"{len(result.warnings)} warning(s))")
        return 1
    bots = result.registry.ids() if result.registry else []
    print(f"\nvalidate-config: OK ({len(bots)} bot(s): {', '.join(bots) or '—'}; "
          f"{len(result.warnings)} warning(s))")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "validate-config":
        print("usage: python -m app.cli validate-config <config_dir>", file=sys.stderr)
        return 2
    return validate_config(argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
