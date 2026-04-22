from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from investigation_agent import config
from investigation_agent.copilot_hardening import filter_tool_definitions
from investigation_agent.integration_contract import build_integration_snapshot, effective_disabled_tools
from investigation_agent.main import app
from investigation_agent.tools import TOOL_DEFINITIONS

"""
Golden integration profiles: expected tool surface vs upstream configuration.

Run with the rest of the suite, or only goldens: pytest -m golden_profile
Excluded from default CI shard when main job uses -m "not golden_profile".
"""
_ALL_TOOLS = frozenset((d.get("function") or {}).get("name") for d in TOOL_DEFINITIONS if isinstance((d.get("function") or {}).get("name"), str))


def _enabled_names(settings) -> frozenset[str]:
    eff = effective_disabled_tools(settings)
    out: set[str] = set()
    for d in filter_tool_definitions(TOOL_DEFINITIONS, eff):
        fn = (d.get("function") or {}).get("name")
        if isinstance(fn, str) and fn.strip():
            out.add(fn.strip())
    return frozenset(out)


def _apply_upstream(
    monkeypatch: pytest.MonkeyPatch,
    *,
    case: bool,
    decision: bool,
    graph: bool,
    hide_without_upstream: bool = True,
) -> None:
    monkeypatch.setattr(config.settings, "case_api_url", "http://case.test" if case else "")
    monkeypatch.setattr(config.settings, "decision_api_url", "http://decision.test" if decision else "")
    monkeypatch.setattr(config.settings, "graph_service_url", "http://graph.test" if graph else "")
    monkeypatch.setattr(config.settings, "copilot_hide_tools_without_upstream", hide_without_upstream)
    monkeypatch.setattr(config.settings, "copilot_disabled_tools", "")


@pytest.mark.golden_profile
@pytest.mark.parametrize(
    "profile,case,decision,graph,hide,expected",
    [
        (
            "full",
            True,
            True,
            True,
            True,
            _ALL_TOOLS,
        ),
        (
            "no_graph",
            True,
            True,
            False,
            True,
            _ALL_TOOLS - frozenset({"subgraph", "get_entity_tags", "subgraph_with_velocity"}),
        ),
        (
            "no_case",
            False,
            True,
            True,
            True,
            _ALL_TOOLS
            - frozenset(
                {
                    "get_case",
                    "list_cases",
                    "export_outcome_labeled_dataset",
                    "ingest_labeled_rows",
                    "get_stored_labeled_dataset",
                    "compare_entity_queue_snapshot",
                },
            ),
        ),
        (
            "no_decision",
            True,
            False,
            True,
            True,
            _ALL_TOOLS
            - frozenset(
                {
                    "get_entity_velocity",
                    "get_decision_audit",
                    "run_replay_ab_comparison",
                    "compare_entity_queue_snapshot",
                },
            ),
        ),
        (
            "case_only",
            True,
            False,
            False,
            True,
            _ALL_TOOLS
            - frozenset(
                {
                    "subgraph",
                    "get_entity_tags",
                    "subgraph_with_velocity",
                    "get_entity_velocity",
                    "get_decision_audit",
                    "run_replay_ab_comparison",
                    "compare_entity_queue_snapshot",
                },
            ),
        ),
        (
            "legacy_visible",
            True,
            False,
            False,
            False,
            _ALL_TOOLS,
        ),
    ],
    ids=["full", "no_graph", "no_case", "no_decision", "case_only", "legacy_visible"],
)
def test_golden_profile_integration_surface(
    profile: str,
    case: bool,
    decision: bool,
    graph: bool,
    hide: bool,
    expected: frozenset[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_upstream(monkeypatch, case=case, decision=decision, graph=graph, hide_without_upstream=hide)
    got = _enabled_names(config.settings)
    assert got == expected, f"profile={profile} mismatch: extra={got - expected} missing={expected - got}"

    snap = build_integration_snapshot(
        config.settings,
        disabled_tools=effective_disabled_tools(config.settings),
    )
    assert snap["tools"]["enabled_count"] == len(expected)
    assert frozenset(snap["tools"]["enabled"]) == expected
    assert snap["contract_version"]


@pytest.mark.golden_profile
@pytest.mark.parametrize(
    "profile,case,decision,graph",
    [
        ("full", True, True, True),
        ("no_graph", True, True, False),
        ("no_case", False, True, True),
        ("no_decision", True, False, True),
        ("case_only", True, False, False),
    ],
)
def test_golden_profile_chat_mode_when_llm_unconfigured(
    profile: str,
    case: bool,
    decision: bool,
    graph: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_upstream(monkeypatch, case=case, decision=decision, graph=graph, hide_without_upstream=True)
    monkeypatch.setattr(config.settings, "openai_api_key", "")
    monkeypatch.setattr(config.settings, "copilot_plain_chat", False)

    async def _fake_tool(*args, **kwargs):
        return {"items": []}

    monkeypatch.setattr("investigation_agent.main._execute_tool", _fake_tool)
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat",
            json={"tenant_id": "demo", "analyst_id": "analyst-1", "messages": [{"role": "user", "content": f"profile={profile}"}]},
        )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("copilot_mode") == "tools_only_deterministic"
    assert "openai_api_key_missing" in (out.get("degraded_reasons") or [])
