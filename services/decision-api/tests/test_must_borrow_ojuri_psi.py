"""Ojuri must-borrow: PSI + promote lifecycle."""

from __future__ import annotations

from decision_api.champion_challenger_audit import (
    drift_promote_gate,
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
