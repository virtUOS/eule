"""Check 14 — graph_params validate against the selected fragment's params model
(docs/03 §graph_params; BUILD_PLAN step 9). One passing + tripping cases per rule."""

from __future__ import annotations

from .conftest import VALID_ENV, make_bot, make_global
from .test_validation import errs


def _tool_agent_bot(**overrides):
    data = dict(
        graph="tool-agent",
        tools={"mcp_servers": [], "allow": ["search_kb"], "deny": []},
        graph_params={},
    )
    data.update(overrides)
    return make_bot(**data)


def c14(bots):
    return [e for e in errs(bots) if "check 14" in e]


def test_valid_params_pass():
    bot = _tool_agent_bot(
        graph_params={"max_tool_rounds": 2, "sources_from": ["search_kb"], "max_tool_result_chars": 1000}
    )
    assert not c14([bot])


def test_empty_params_pass_defaults():
    assert not c14([_tool_agent_bot()])


def test_unknown_param_key_rejected():
    bad = _tool_agent_bot(graph_params={"max_tool_rouds": 2})  # typo
    found = c14([bad])
    assert found and "max_tool_rouds" in found[0]


def test_wrong_type_rejected():
    assert c14([_tool_agent_bot(graph_params={"max_tool_rounds": "three"})])


def test_out_of_range_rejected():
    assert c14([_tool_agent_bot(graph_params={"max_tool_rounds": 0})])
    assert c14([_tool_agent_bot(graph_params={"max_tool_rounds": 6})])


def test_sources_from_outside_allowlist_rejected():
    bad = _tool_agent_bot(graph_params={"sources_from": ["not_allowed"]})
    found = c14([bad])
    assert found and "not_allowed" in found[0]


def test_sources_from_denied_tool_rejected():
    # deny wins over allow: a denied tool is not in the EFFECTIVE allowlist
    bad = _tool_agent_bot(
        tools={"mcp_servers": [], "allow": ["search_kb"], "deny": ["search_kb"]},
        graph_params={"sources_from": ["search_kb"]},
    )
    assert [e for e in c14([bad]) if "sources_from" in e]


def test_tool_agent_requires_nonempty_effective_allowlist():
    bad = _tool_agent_bot(tools={"mcp_servers": [], "allow": [], "deny": []})
    found = c14([bad])
    assert found and "non-empty" in found[0]


def test_graph_params_on_bespoke_fragment_rejected():
    # bespoke fragments take no params — a stray block fails boot, never silently ignored
    bad = make_bot(graph="echo", graph_params={"max_tool_rounds": 1})
    assert c14([bad])


def test_passthrough_takes_no_params():
    assert not c14([make_bot(graph="passthrough")])
    assert c14([make_bot(graph="passthrough", graph_params={"anything": 1})])


def test_fragment_registries_cover_same_graphs():
    """A fragment registered without a params model would make check 14 silently skip
    it. The module fails at import on divergence; this pins the invariant."""
    from app.graphs.registry import FRAGMENT_BUILDERS, FRAGMENT_PARAM_MODELS

    assert FRAGMENT_BUILDERS.keys() == FRAGMENT_PARAM_MODELS.keys()


def test_unknown_graph_reports_check13_not_14():
    bad = make_bot(graph="ghost", graph_params={"x": 1})
    all_errors = errs([bad])
    assert [e for e in all_errors if "check 13" in e]
    assert not [e for e in all_errors if "check 14" in e]  # skipped when graph unknown
