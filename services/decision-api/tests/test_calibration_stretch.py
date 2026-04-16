"""Stretch: calibration snapshots + trusted zones file load."""

from __future__ import annotations

import json
from unittest.mock import patch

from decision_api.calibration_api import compute_drift_for_tenant
from decision_api.trusted_zones import load_trusted_zones_for_tenant


def test_trusted_zones_from_file(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    cal = rules / "calibration_data"
    cal.mkdir(parents=True)
    zpath = cal / "trusted_zones_t1.json"
    zpath.write_text(
        json.dumps([{"lat": 1.0, "lon": 2.0, "radius_km": 10, "label": "hq"}]),
        encoding="utf-8",
    )
    with patch("decision_api.trusted_zones.settings") as m:
        m.rules_path = str(rules)
        zones = load_trusted_zones_for_tenant("t1")
    assert len(zones) == 1
    assert zones[0]["label"] == "hq"


def test_drift_compute(tmp_path):
    ref = {
        "integrity_histogram": {"a": 50, "b": 50},
        "mean_integrity": 0.5,
        "sample_count": 100,
        "set_at": "2026-01-01T00:00:00+00:00",
    }
    ref_path = tmp_path / "reference_default.json"
    ref_path.write_text(json.dumps(ref), encoding="utf-8")
    snap = {
        "ts": "2026-02-01T00:00:00+00:00",
        "tenant_id": "acme",
        "profile": "default",
        "sample_count": 100,
        "integrity_histogram": {"a": 60, "b": 40},
    }
    snap_path = tmp_path / "snapshots.jsonl"
    snap_path.write_text(json.dumps(snap) + "\n", encoding="utf-8")
    data = compute_drift_for_tenant("acme", "default", snapshots_path=snap_path, reference_path=ref_path)
    assert data.get("drift_score") is not None
    assert data["hint"] in ("ok", "moderate_drift_monitor", "elevated_bin_shift_review_calibration")
