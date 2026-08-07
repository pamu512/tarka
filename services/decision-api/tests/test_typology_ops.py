"""Tazama must-borrow: typology ops control plane."""

from __future__ import annotations

from decision_api.typology_ops import (
    aggregate_typology_breaches_from_audits,
    load_typology_ops_posture,
)


def test_typology_ops_posture_configured():
    out = load_typology_ops_posture()
    assert out["schema_id"] == "tarka.typology_ops_posture/v1"
    assert out["control_plane"]["typology_count"] >= 1
    assert "Tazama" in out["borrowed_from"]
    assert "ISO 20022" in out["vs_tazama"]


def test_aggregate_typology_breaches_from_audits():
    hist = aggregate_typology_breaches_from_audits(
        [
            {
                "payload_snapshot": {
                    "typology_summary": {
                        "highest_breach": "alert",
                        "driver_typology_id": "mule_rail",
                    }
                }
            },
            {
                "payload_snapshot": {
                    "typology_summary": {
                        "highest_breach": "pass",
                        "driver_typology_id": None,
                    }
                }
            },
            {"payload_snapshot": {}},
        ]
    )
    assert hist["rows_with_typology_summary"] == 2
    assert hist["highest_breach_counts"]["alert"] == 1
    assert hist["driver_typology_counts"]["mule_rail"] == 1
    out = load_typology_ops_posture(audit_breach_histogram=hist)
    assert out["audit_breach_histogram"]["alert_or_warning_rows"] == 1
