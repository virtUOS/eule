"""Validation checks 1–12 (docs/03) — one passing + one tripping case per check,
plus loader-level enforcement (dead `overlay`, stale fields, id uniqueness/filename)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.registry.loader import load_and_validate
from app.registry.models import BotCfg
from app.registry.validation import check_all

from .conftest import VALID_ENV, make_bot, make_global


def errs(bots, env=VALID_ENV, gcfg=None):
    gcfg = gcfg or make_global()
    e, _w = check_all(gcfg, {b.id: b for b in bots}, env)
    return e


def warns(bots, env=VALID_ENV, gcfg=None):
    gcfg = gcfg or make_global()
    _e, w = check_all(gcfg, {b.id: b for b in bots}, env)
    return w


# 1 — model.provider exists
def test_check1():
    assert not [e for e in errs([make_bot()]) if "check 1" in e]
    assert [e for e in errs([make_bot(model={"provider": "ghost"})]) if "check 1" in e]


# 2 — tools.mcp_servers exist
def test_check2():
    assert not [e for e in errs([make_bot()]) if "check 2" in e]
    bad = make_bot(tools={"mcp_servers": ["ghost"]})
    assert [e for e in errs([bad]) if "check 2" in e]


# 3 — *_env references resolve
def test_check3():
    assert not [e for e in errs([make_bot()], env=VALID_ENV) if "check 3" in e]
    assert [e for e in errs([make_bot()], env={}) if "check 3" in e]


# 4 — id regex
def test_check4():
    assert not [e for e in errs([make_bot(id="course-catalog")]) if "check 4" in e]
    assert [e for e in errs([make_bot(id="Bad_Id")]) if "check 4" in e]


# 5 — requires_auth ⇒ identity ⇒ global auth
def test_check5():
    auth_global = make_global(
        auth={
            "issuer": "https://sso/realms/x",
            "jwks_url": "https://sso/certs",
            "audience": "chatbots",
        }
    )
    ok = make_bot(requires_auth=True, identity={"subject_claim": "sub"})
    assert not [e for e in errs([ok], gcfg=auth_global) if "check 5" in e]
    # tripping: requires_auth but no identity and no global auth
    bad = make_bot(requires_auth=True)
    assert [e for e in errs([bad]) if "check 5" in e]


# 6 — guard.enabled ⇒ guard.provider resolves
def test_check6():
    ok = make_bot(guard={"enabled": True, "provider": "default"})
    assert not [e for e in errs([ok]) if "check 6" in e]
    bad = make_bot(guard={"enabled": True})
    assert [e for e in errs([bad]) if "check 6" in e]
    bad2 = make_bot(guard={"enabled": True, "provider": "ghost"})
    assert [e for e in errs([bad2]) if "check 6" in e]


# 7 — WARN public no-auth non-router bot with guard disabled
def test_check7():
    assert [w for w in warns([make_bot()]) if "check 7" in w]  # guard off → warn
    guarded = make_bot(guard={"enabled": True, "provider": "default"})
    assert not [w for w in warns([guarded]) if "check 7" in w]


# 8 — override shape enforced by schema
def test_check8_schema_enforced():
    with pytest.raises(ValidationError):
        make_bot(guard="on")  # guard must be an object, not a string
    with pytest.raises(ValidationError):
        make_bot(rate_limit={"anonymous": {"requests_per_min": "lots"}})


# 9 — theme contrast against resolved tokens
def test_check9():
    assert not [e for e in errs([make_bot()]) if "check 9" in e]
    # pale primary as link text on white → fails 4.5:1
    pale = make_bot(theme={"light": {"--primary": "#f7c9d6"}})
    assert [e for e in errs([pale]) if "check 9" in e]


# 10 — routes target exists / enabled / not self
def test_check10():
    faq = make_bot(id="faq", name="FAQ")
    router = make_bot(
        id="assistant", name="Assistant",
        routes={"targets": [{"bot": "faq", "label": "FAQ"}]},
    )
    assert not [e for e in errs([router, faq]) if "check 10" in e]

    missing = make_bot(id="assistant", routes={"targets": [{"bot": "ghost", "label": "X"}]})
    assert [e for e in errs([missing]) if "check 10" in e]

    selfref = make_bot(id="assistant", routes={"targets": [{"bot": "assistant", "label": "X"}]})
    assert [e for e in errs([selfref]) if "check 10" in e]

    disabled = make_bot(id="faq", name="FAQ", enabled=False)
    router2 = make_bot(id="assistant", routes={"targets": [{"bot": "faq", "label": "FAQ"}]})
    assert [e for e in errs([router2, disabled]) if "check 10" in e]


# 11 — auth-posture invariant (public router may not route to auth bot)
def test_check11():
    auth_global = make_global(
        auth={"issuer": "https://sso", "jwks_url": "https://sso/certs", "audience": "chatbots"}
    )
    authbot = make_bot(id="enrollment", requires_auth=True, identity={"subject_claim": "sub"})
    public_router = make_bot(
        id="assistant", requires_auth=False,
        routes={"targets": [{"bot": "enrollment", "label": "Enrollment"}]},
    )
    assert [e for e in errs([public_router, authbot], gcfg=auth_global) if "check 11" in e]

    # an authenticated router MAY include an auth bot
    auth_router = make_bot(
        id="portal", requires_auth=True, identity={"subject_claim": "sub"},
        routes={"targets": [{"bot": "enrollment", "label": "Enrollment"}]},
    )
    assert not [e for e in errs([auth_router, authbot], gcfg=auth_global) if "check 11" in e]


# 12 — routes.mode ∈ {menu} for v1
def test_check12():
    ok = make_bot(id="assistant", routes={"mode": "menu", "targets": []})
    assert not [e for e in errs([ok]) if "check 12" in e]
    bad = make_bot(id="assistant", routes={"mode": "classifier", "targets": []})
    assert [e for e in errs([bad]) if "check 12" in e]


# --- loader-level enforcement ----------------------------------------------

import yaml

_GLOBAL = {
    "version": 1,
    "model_providers": {"default": {"base_url": "http://x/v1", "api_key_env": "VLLM_API_KEY"}},
    "theme": {
        "dark_mode": "auto",
        "light": {"--bg": "#ffffff", "--surface": "#f4f4f5", "--text": "#18181b",
                  "--text-muted": "#6b6b70", "--primary": "#a6093d",
                  "--accent": "#f2c879", "--on-primary": "#ffffff"},
        "dark": {"--bg": "#161618", "--surface": "#1e1e21", "--text": "#f4f4f5",
                 "--text-muted": "#9a9aa1", "--primary": "#d95c7d",
                 "--accent": "#f2c879", "--on-primary": "#ffffff"},
    },
}


def _echo_dict(bot_id="echo", mode="launcher", extra=None):
    d = {
        "version": 1,
        "id": bot_id,
        "name": "Echo",
        "model": {"provider": "default"},
        "requires_auth": False,
        "embedding": {"mode": mode, "allowed_origins": []},
    }
    if extra:
        d.update(extra)
    return d


def _write(tmp_path, bots: dict[str, dict], global_cfg: dict | None = None):
    (tmp_path / "bots").mkdir(parents=True, exist_ok=True)
    (tmp_path / "global.yaml").write_text(yaml.safe_dump(global_cfg or _GLOBAL))
    for name, cfg in bots.items():
        (tmp_path / "bots" / name).write_text(yaml.safe_dump(cfg))
    return tmp_path


def test_loader_rejects_dead_overlay_mode(tmp_path):
    d = _write(tmp_path, {"echo.yaml": _echo_dict(mode="overlay")})
    result = load_and_validate(d, env=VALID_ENV)
    assert not result.ok
    assert any("mode" in e for e in result.errors)


def test_loader_accepts_launcher_mode(tmp_path):
    d = _write(tmp_path, {"echo.yaml": _echo_dict(mode="launcher")})
    result = load_and_validate(d, env=VALID_ENV)
    assert result.ok, result.errors


def test_loader_rejects_stale_field(tmp_path):
    # A stale OLD-spec field (`form`) must fail boot, not be silently ignored.
    d = _write(tmp_path, {"echo.yaml": _echo_dict(extra={"form": {}})})
    result = load_and_validate(d, env=VALID_ENV)
    assert not result.ok


def test_loader_filename_must_match_id(tmp_path):
    d = _write(tmp_path, {"wrong.yaml": _echo_dict(bot_id="echo")})
    result = load_and_validate(d, env=VALID_ENV)
    assert any("filename stem" in e for e in result.errors)


def test_loader_duplicate_id(tmp_path):
    d = _write(tmp_path, {"echo.yaml": _echo_dict(), "dup.yaml": _echo_dict()})
    result = load_and_validate(d, env=VALID_ENV)
    assert any("duplicate bot id" in e for e in result.errors)


def test_real_config_is_valid():
    from .conftest import CONFIG_DIR

    result = load_and_validate(CONFIG_DIR, env=VALID_ENV)
    assert result.ok, result.errors
