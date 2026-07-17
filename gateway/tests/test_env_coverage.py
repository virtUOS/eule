"""Guard against the recurring drift where a new `*_env` reference is added to config
but a dummy value is forgotten in one of the places that must list it — surfacing only
as a check-3 failure at `validate-config` time. This asserts, at the source, that every
env name referenced by config is covered by all three lists."""

from __future__ import annotations

import yaml

from .conftest import CONFIG_DIR, REPO_ROOT, VALID_ENV


def _referenced_env_names() -> set[str]:
    """Every `*_env` reference in global.yaml (provider api keys + MCP bearer tokens)."""
    gcfg = yaml.safe_load((CONFIG_DIR / "global.yaml").read_text())
    names: set[str] = set()
    for provider in (gcfg.get("model_providers") or {}).values():
        if provider.get("api_key_env"):
            names.add(provider["api_key_env"])
    for server in (gcfg.get("mcp_servers") or {}).values():
        if server.get("bearer_token_env"):
            names.add(server["bearer_token_env"])
    return names


def test_valid_env_covers_config() -> None:
    missing = _referenced_env_names() - set(VALID_ENV)
    assert not missing, f"add to VALID_ENV in tests/conftest.py: {sorted(missing)}"


def test_ci_gateway_env_covers_config() -> None:
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    ci_env = ci["jobs"]["gateway"].get("env") or {}
    missing = _referenced_env_names() - set(ci_env)
    assert not missing, f"add to the gateway job env in .github/workflows/ci.yml: {sorted(missing)}"


def test_env_example_covers_config() -> None:
    keys = {
        line.split("=", 1)[0].strip()
        for line in (REPO_ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = _referenced_env_names() - keys
    assert not missing, f"add to .env.example: {sorted(missing)}"
