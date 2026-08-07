"""Tazama must-borrow: typology ops control plane."""

from __future__ import annotations

from decision_api.typology_ops import load_typology_ops_posture


def test_typology_ops_posture_configured():
    out = load_typology_ops_posture()
    assert out["schema_id"] == "tarka.typology_ops_posture/v1"
    assert out["control_plane"]["typology_count"] >= 1
    assert "Tazama" in out["borrowed_from"]
    assert "ISO 20022" in out["vs_tazama"]
