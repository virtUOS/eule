"""Theme resolution + WCAG contrast (docs/03 check 9, docs/05 §8)."""

from __future__ import annotations

from app.registry.theme import (
    contrast_ratio,
    contrast_violations,
    resolve_theme,
)

from .conftest import make_global


def test_contrast_ratio_known_values():
    assert round(contrast_ratio("#000000", "#ffffff"), 1) == 21.0
    assert round(contrast_ratio("#ffffff", "#ffffff"), 1) == 1.0


def test_deployment_theme_passes():
    theme = resolve_theme(make_global().theme)
    assert contrast_violations(theme) == []


def test_pale_primary_fails():
    g = make_global()
    g.theme.light["--primary"] = "#f7c9d6"  # pale pink
    assert any("--primary" in v for v in contrast_violations(resolve_theme(g.theme)))


def test_auto_on_primary_resolves_by_luminance():
    from app.registry.models import ThemeOverride

    g = make_global()
    # Dark red primary → white on-primary; near-white primary → black.
    dark = resolve_theme(g.theme, ThemeOverride(light={"--primary": "#7a0019", "--on-primary": "auto"}))
    assert dark.light["--on-primary"] == "#ffffff"
    light = resolve_theme(g.theme, ThemeOverride(light={"--primary": "#f2c879", "--on-primary": "auto"}))
    assert light.light["--on-primary"] == "#000000"


def test_per_bot_override_deep_merges_over_deployment():
    from app.registry.models import ThemeOverride

    g = make_global()
    resolved = resolve_theme(g.theme, ThemeOverride(light={"--primary": "#7a0019"}))
    assert resolved.light["--primary"] == "#7a0019"
    # untouched tokens inherit the deployment theme
    assert resolved.light["--bg"] == g.theme.light["--bg"]
