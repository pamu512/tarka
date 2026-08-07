"""Ojuri must-borrow: PSI + promote lifecycle + McNemar p-value + labeled F1."""

from __future__ import annotations

from decision_api.champion_challenger_audit import (
    drift_promote_gate,
    labeled_champion_challenger_f1,
    mcnemar_pvalue,
    population_stability_index,
    promote_lifecycle_stage,
)


def test_psi_identical_histograms_near_zero():
    h = {"a": 10, "b": 10, "c": 10}
    psi = population_stability_index(h, h)
    assert psi is not None
    assert psi < 1e-9


def test_psi_shifted_histograms_elevated():
    ref = {"a": 90, "b": 10}
    cur = {"a": 10, "b": 90}
    psi = population_stability_index(ref, cur)
    assert psi is not None
    assert psi > 0.25


def test_drift_gate_blocks_high_psi():
    gate = drift_promote_gate({"hint": "ok", "drift_score": 0.05, "psi": 0.4})
    assert gate["promote_allowed"] is False
    assert any("psi>" in b for b in gate["blockers"])


def test_promote_lifecycle_stages():
    assert (
        promote_lifecycle_stage(
            label_ok=False, mcnemar_ok=False, drift_ok=False, desk_ok=False
        )["stage"]
        == "CANDIDATE"
    )
    assert (
        promote_lifecycle_stage(
            label_ok=True, mcnemar_ok=False, drift_ok=True, desk_ok=False
        )["stage"]
        == "SHADOW"
    )
    assert (
        promote_lifecycle_stage(
            label_ok=True, mcnemar_ok=True, drift_ok=True, desk_ok=True
        )["stage"]
        == "ACTIVE"
    )


def test_mcnemar_pvalue_skewed_significant():
    out = mcnemar_pvalue(20, 0)
    assert out["method"] == "exact_binomial"
    assert out["p_value"] is not None
    assert out["p_value"] < 0.001


def test_mcnemar_pvalue_balanced_not_significant():
    out = mcnemar_pvalue(12, 13)
    assert out["p_value"] is not None
    assert out["p_value"] > 0.5


def test_labeled_champion_challenger_f1():
    audits = [
        {
            "trace_id": "t1",
            "payload_snapshot": {
                "policy_routing": {
                    "champion_decision": "review",
                    "challenger_decision": "allow",
                }
            },
        },
        {
            "trace_id": "t2",
            "payload_snapshot": {
                "policy_routing": {
                    "champion_decision": "allow",
                    "challenger_decision": "review",
                }
            },
        },
        {
            "trace_id": "t3",
            "payload_snapshot": {
                "policy_routing": {
                    "champion_decision": "review",
                    "challenger_decision": "review",
                }
            },
        },
    ]
    out = labeled_champion_challenger_f1(
        audits, by_trace={"t1": "1", "t2": "0", "t3": "1"}
    )
    assert out["labeled_rows"] == 3
    assert out["champion_f1"] is not None
    assert out["challenger_f1"] is not None
