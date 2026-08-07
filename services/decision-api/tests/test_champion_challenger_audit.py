"""P0-CC: champion–challenger aggregate + label-gated promote."""

from __future__ import annotations

from decision_api.champion_challenger_audit import (
    aggregate_champion_challenger,
    drift_promote_gate,
    label_gated_promote,
    mcnemar_promote_gate,
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


def test_mcnemar_promote_gate_blocks_underpowered():
    cc = aggregate_champion_challenger(
        [
            {
                "trace_id": "t1",
                "payload_snapshot": {
                    "policy_routing": {
                        "champion_decision": "allow",
                        "challenger_decision": "review",
                        "decisions_agree": False,
                    }
                },
            }
        ]
    )
    gate = mcnemar_promote_gate(cc, min_discordant_pairs=20)
    assert gate["promote_allowed"] is False
    assert gate["discordant_pairs"] == 1
    assert any("discordant_pairs" in b for b in gate["blockers"])


def test_drift_promote_gate_blocks_elevated():
    gate = drift_promote_gate(
        {"hint": "elevated_bin_shift_review_calibration", "drift_score": 0.4}
    )
    assert gate["promote_allowed"] is False
    assert "calibration_drift_elevated" in gate["blockers"]


def test_drift_promote_gate_allows_ok():
    gate = drift_promote_gate({"hint": "ok", "drift_score": 0.05})
    assert gate["promote_allowed"] is True


def test_mcnemar_promote_gate_allows_enough_discordant():
    audits = []
    for i in range(25):
        audits.append(
            {
                "trace_id": f"t{i}",
                "payload_snapshot": {
                    "policy_routing": {
                        "champion_decision": "allow",
                        "challenger_decision": "review",
                        "decisions_agree": False,
                    }
                },
            }
        )
    gate = mcnemar_promote_gate(
        aggregate_champion_challenger(audits), min_discordant_pairs=20
    )
    assert gate["promote_allowed"] is True
    assert gate["discordant_pairs"] == 25
