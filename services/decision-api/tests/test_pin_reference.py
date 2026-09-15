"""Drift reference pinning — live-loop demonstration of the existing API.

``POST /v1/calibration/reference/{profile}`` pins a golden distribution;
``compute_drift_for_tenant`` compares the latest snapshot against it. These
tests pin what the endpoint contract actually promises so the capability
stays demonstration-tier: pin → snapshot drift → score.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SRC / "src"))

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


@pytest.fixture()
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    return tmp_path


def _client():
    from fastapi.testclient import TestClient

    from decision_api.main import app

    return TestClient(app)


def _snap(hist: dict, at: str) -> dict:
    return {
        "tenant_id": "acme",
        "profile": "default",
        "sample_count": sum(hist.values()),
        "integrity_histogram": hist,
        "label_source_counts": {},
        "snapshot_at": at,
    }


def test_pin_reference_then_identical_snapshot_zero_drift(temp_data_dir) -> None:
    from decision_api.calibration_api import compute_drift_for_tenant

    client = _client()
    golden = {"0.0-0.2": 70, "0.2-0.4": 20, "0.4-0.6": 10}
    assert client.post("/v1/calibration/reference/default", json=_snap(golden, "2026-09-15T00:00:00Z")).status_code == 200
    assert client.post("/v1/calibration/snapshots", json=_snap(golden, "2026-09-15T01:00:00Z")).status_code == 201
    drift = compute_drift_for_tenant("acme", "default")
    assert drift["drift_score"] == 0.0
    assert drift["hint"] == "ok"
    assert drift["psi"] is not None


def test_pin_reference_detects_shifted_distribution(temp_data_dir) -> None:
    from decision_api.calibration_api import compute_drift_for_tenant

    client = _client()
    golden = {"0.0-0.2": 70, "0.2-0.4": 20, "0.4-0.6": 10}
    client.post("/v1/calibration/reference/default", json=_snap(golden, "2026-09-15T00:00:00Z"))
    shifted = {"0.0-0.2": 20, "0.2-0.4": 30, "0.4-0.6": 50}  # mass moved right
    client.post("/v1/calibration/snapshots", json=_snap(shifted, "2026-09-15T02:00:00Z"))
    drift = compute_drift_for_tenant("acme", "default")
    assert drift["drift_score"] > 0.1, drift
    assert drift["hint"] == "elevated_bin_shift_review_calibration"


def test_pin_persists_reference_file(temp_data_dir) -> None:
    client = _client()
    hist = {"allow": 9, "deny": 1}
    client.post("/v1/calibration/reference/default", json=_snap(hist, "2026-09-15T00:00:00Z"))
    data = json.loads((temp_data_dir / "references.json").read_text())
    assert data["default"]["integrity_histogram"] == hist
