"""Safe-action gate for high-impact tool calls (Q2-E02)."""

from __future__ import annotations

from investigation_agent.copilot_hardening import check_safe_action_gate


def test_high_impact_tool_blocked_without_allowlist() -> None:
    high = frozenset({"ingest_labeled_rows"})
    allowed, err = check_safe_action_gate(
        "ingest_labeled_rows",
        high_impact_tools=high,
        safe_action_allowlist=frozenset(),
        reviewer_secret="secret",
        reviewer_header="",
    )
    assert allowed is False
    assert err == "safe_action_blocked:high_impact_tool_not_allowlisted"


def test_high_impact_tool_permitted_with_reviewer_secret() -> None:
    high = frozenset({"run_replay_ab_comparison"})
    allowed, err = check_safe_action_gate(
        "run_replay_ab_comparison",
        high_impact_tools=high,
        safe_action_allowlist=frozenset(),
        reviewer_secret="secret",
        reviewer_header="secret",
    )
    assert allowed is True
    assert err is None


def test_high_impact_tool_permitted_on_allowlist() -> None:
    high = frozenset({"screen_sanctions_pep"})
    allowed, err = check_safe_action_gate(
        "screen_sanctions_pep",
        high_impact_tools=high,
        safe_action_allowlist=frozenset({"screen_sanctions_pep"}),
        reviewer_secret="",
        reviewer_header="",
    )
    assert allowed is True
    assert err is None
