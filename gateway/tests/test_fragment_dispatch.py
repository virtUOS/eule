"""Prereq C — fragment dispatch: BotCfg.graph resolves via the fragment registry,
not a hardcoded echo fragment (docs/03 check 13)."""

from __future__ import annotations

import pytest

from app.graphs.factory import build_compiled_graph
from app.graphs.registry import FRAGMENT_BUILDERS, UnknownGraph, build_fragment, known_graphs
from app.registry.registry import Registry
from app.registry.validation import check_all

from .conftest import make_bot, make_global


def test_known_graphs_includes_echo():
    assert "echo" in known_graphs()


def test_build_fragment_resolves_echo():
    cfg = make_bot(graph="echo")
    frag = build_fragment(cfg)
    assert frag is not None


def test_build_fragment_raises_on_unknown_graph():
    cfg = make_bot(graph="does-not-exist")
    with pytest.raises(UnknownGraph):
        build_fragment(cfg)


def test_factory_uses_the_configured_graph_not_hardcoded_echo(sessions):
    calls: list[str] = []
    FRAGMENT_BUILDERS["_probe"] = lambda cfg: (calls.append(cfg.id) or FRAGMENT_BUILDERS["echo"](cfg))
    try:
        cfg = make_bot(id="probe-bot", graph="_probe")
        reg = Registry(make_global(), {"probe-bot": cfg})
        build_compiled_graph(cfg, sessions.checkpointer, reg)
        assert calls == ["probe-bot"]  # the factory dispatched to OUR builder, not echo's
    finally:
        del FRAGMENT_BUILDERS["_probe"]


# --- check 13 --------------------------------------------------------------

def test_check13_known_graph_passes():
    errors, _ = check_all(make_global(), {"echo": make_bot(id="echo", graph="echo")}, {})
    assert not [e for e in errors if "check 13" in e]


def test_check13_unknown_graph_fails_boot():
    bad = make_bot(id="broken", graph="nope")
    errors, _ = check_all(make_global(), {"broken": bad}, {})
    assert any("check 13" in e and "nope" in e for e in errors)
