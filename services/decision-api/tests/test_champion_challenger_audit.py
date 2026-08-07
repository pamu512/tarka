"""P0-CC: champion–challenger aggregate + label-gated promote."""

from __future__ import annotations

from decision_api.champion_challenger_audit import (
    aggregate_champion_challenger,
    label_gated_promote,
)


def test_aggregate_agreement_rate():
    audits = [
        {
            "trace_id": "t1",
            "payload_snapshot": {
                "policy_routing": {
                    "champion_decision": "allow",
                    "challenger_decision": "allow",
                    "decisions_agree": True,
                    "champion_rule_score": 1.0,
                    "challenger_rule_score": 1.0,
                }
            },
        },
        {
            "trace_id": "t2",
            "payload_snapshot": {
                "policy_routing": {
                    "champion_decision": "allow",
                    "challenger_decision": "review",
                    "decisions_agree": False,
                    "champion_rule_score": 1.0,
                    "challenger_rule_score": 40.0,
                }
            },
        },
    ]
    out = aggregate_champion_challenger(audits)
    assert out["rows_with_policy_routing"] == 2
    assert out["decisions_agree_count"] == 1
    assert out["decision_agreement_rate"] == 0.5
    assert out["mcnemar_contingency"]["b_champion_allow_challenger_stricter"] == 1
    assert len(out["audit_rows"]) == 2


def test_label_gated_promote_blocks_proxy():
    gate = label_gated_promote(
        label_posture={
            "healthy": False,
            "status": "insufficient_labels",
            "label_source": "proxy_from_decision",
            "label_coverage": 0.05,
        }
    )
    assert gate["promote_allowed"] is False
    assert "insufficient_labels" in gate["blockers"]
    assert "proxy_labels_only" in gate["blockers"]


def test_label_gated_promote_allows_healthy():
    gate = label_gated_promote(
        label_posture={
            "healthy": True,
            "status": "ok",
            "label_coverage": 0.5,
            "label_source": "ground_truth",
        }
    )
    assert gate["promote_allowed"] is True
    assert gate["blockers"] == []
