from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_calibration_publish_activate_score_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CALIBRATION_SERVICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.delenv("API_KEYS", raising=False)
    from ml_scoring import main as scoring_main

    scoring_main._valid_api_keys = None
    app = scoring_main.app
    with TestClient(app) as client:
        pub = client.post(
            "/v1/calibrate/profiles",
            json={
                "tenant_id": "t1",
                "profile_id": "default",
                "version": 2,
                "expected_calibration_version": 7,
                "bands": [
                    {"min": 0.0, "max": 0.5, "adjustment": 0.05},
                    {"min": 0.5, "max": 1.0, "adjustment": -0.03},
                ],
            },
        )
        assert pub.status_code == 201
        got = client.get("/v1/calibrate/profiles/t1/default")
        assert got.status_code == 200
        assert got.json()["version"] == 2

        act = client.post("/v1/calibrate/profiles/t1/default/activate", json={"version": 2})
        assert act.status_code == 200
        assert act.json()["ok"] is True

        snap = client.post(
            "/v1/calibrate/snapshots",
            json={
                "tenant_id": "t1",
                "profile_id": "default",
                "sample_count": 20,
                "mean_integrity": 0.8,
            },
        )
        assert snap.status_code == 201
        drift = client.get("/v1/calibrate/drift", params={"tenant_id": "t1", "profile_id": "default"})
        assert drift.status_code == 200
        assert "hint" in drift.json()

        score = client.post(
            "/v1/calibrate/score",
            json={
                "tenant_id": "t1",
                "profile_id": "default",
                "baseline_confidence": 0.42,
                "features": {"event_count_1h": 18},
            },
        )
        assert score.status_code == 200
        data = score.json()
        assert data["profile_version"] == 2
        assert data["expected_calibration_version"] == 7
        assert 0 <= data["calibrated_confidence"] <= 1

