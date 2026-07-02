"""Theme resolution + WCAG contrast (docs/03 check 9, docs/05 §8).

`resolve_theme` merges a per-bot override over the deployment theme and resolves any
`--on-primary: "auto"` to black/white by luminance. The contrast guardrail runs against
the *resolved* token sets, so a pale `--primary` shipped by an external client fails
boot rather than producing illegible links or a washed-out send icon.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ThemeOverride, ThemeTokens

_BLACK = "#000000"
_WHITE = "#ffffff"


@dataclass(frozen=True)
class ResolvedTheme:
    light: dict[str, str]
    dark: dict[str, str]
    radius: dict[str, str] = field(default_factory=dict)
    dark_mode: str = "auto"


def _parse_hex(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _channel(c: int) -> float:
    s = c / 255.0
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    r, g, b = _parse_hex(hex_color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _auto_on_primary(primary: str) -> str:
    """Pick black or white for `--on-primary` by whichever contrasts better."""
    return _WHITE if contrast_ratio(_WHITE, primary) >= contrast_ratio(_BLACK, primary) else _BLACK


def _merge_scheme(base: dict[str, str], override: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    merged.update(override)
    if merged.get("--on-primary") == "auto":
        # Resolve "auto" only when --primary is a usable colour; otherwise leave the
        # literal "auto" so the contrast check reports a clean check-9 error rather
        # than raising here (missing/invalid --primary is caught by _scheme_violations).
        primary = merged.get("--primary")
        if primary is not None:
            try:
                merged["--on-primary"] = _auto_on_primary(primary)
            except ValueError:
                pass
    return merged


def resolve_theme(theme: ThemeTokens, override: ThemeOverride | None = None) -> ResolvedTheme:
    ov = override or ThemeOverride()
    radius = dict(theme.radius)
    radius.update(ov.radius)
    return ResolvedTheme(
        light=_merge_scheme(theme.light, ov.light),
        dark=_merge_scheme(theme.dark, ov.dark),
        radius=radius,
        dark_mode=ov.dark_mode or theme.dark_mode,
    )


# --- contrast guardrail (check 9) ------------------------------------------

_TEXT_MIN = 4.5   # WCAG 1.4.3 normal text
_UI_MIN = 3.0     # WCAG 1.4.11 non-text / graphical (icons on primary)


def _scheme_violations(scheme: str, t: dict[str, str]) -> list[str]:
    out: list[str] = []

    def need(fg_key: str, bg_key: str, minimum: float, why: str) -> None:
        fg, bg = t.get(fg_key), t.get(bg_key)
        if fg is None or bg is None:
            out.append(f"[{scheme}] missing token for contrast pair {fg_key} on {bg_key}")
            return
        try:
            ratio = contrast_ratio(fg, bg)
        except ValueError:
            # Non-hex token value (e.g. a named colour or rgb()) — report cleanly
            # instead of letting the ValueError abort validate-config with a traceback.
            out.append(
                f"[{scheme}] {fg_key} or {bg_key} is not a hex colour "
                f"({fg_key}={fg!r}, {bg_key}={bg!r}); theme tokens must be #rgb/#rrggbb"
            )
            return
        if ratio + 1e-9 < minimum:
            out.append(
                f"[{scheme}] {fg_key} on {bg_key} = {ratio:.2f}:1 (< {minimum}:1) — {why}"
            )

    # --primary as TEXT on --bg (links, starter chips, quick-reply chips)
    need("--primary", "--bg", _TEXT_MIN, "links/chips")
    # body + muted text
    need("--text", "--bg", _TEXT_MIN, "body text")
    need("--text-muted", "--bg", _TEXT_MIN, "muted text on bg")
    need("--text-muted", "--surface", _TEXT_MIN, "muted text on surface")
    # icons/text on primary surfaces (launcher, send) — graphical
    need("--on-primary", "--primary", _UI_MIN, "icon on primary")
    # --accent is decorative (eyebrow glyph) → EXEMPT
    return out


def contrast_violations(theme: ResolvedTheme) -> list[str]:
    return _scheme_violations("light", theme.light) + _scheme_violations("dark", theme.dark)
