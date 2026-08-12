"""Feature-store ops posture — Feast/Flink claims stay fail-closed."""

from __future__ import annotations

import json

from decision_api.feature_store_posture import (
    dual_diff_proven,
    load_feature_store_ops_posture,
)


def test_dual_diff_proven_requires_matched():
    assert dual_diff_proven(None) is False
    assert dual_diff_proven({"mode": "dry_run", "ok": True}) is False
    assert (
        dual_diff_proven(
            {
                "schema_id": "tarka.counter_parity/v1",
                "mode": "dual_diff",
                "matched": True,
            }
        )
        is True
    )
    assert (
        dual_diff_proven(
            {
                "schema_id": "tarka.counter_parity/v1",
                "mode": "dual_diff",
                "matched": False,
            }
        )
        is False
    )


def test_ops_posture_fail_closed_without_artifact(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("TARKA_REDIS_URL", raising=False)
    out = load_feature_store_ops_posture(rules_path=str(tmp_path), redis_url="")
    assert out["schema_id"] == "tarka.feature_store_ops_posture/v1"
    assert out["feast_class_claim_allowed"] is False
    assert out["streaming_flink_claim_allowed"] is False
    assert out["ops_ready"] is False
    assert "dual_diff_not_proven" in out["blockers"]
    assert "redis_online_unconfigured" in out["blockers"]
    assert out["manifest"]["feature_count"] >= 1
    assert "flink" in out["streaming_plane"]["not"]


def test_ops_ready_when_redis_and_dual_diff(tmp_path):
    artifact = {
        "schema_id": "tarka.counter_parity/v1",
        "mode": "dual_diff",
        "matched": True,
        "ts": "2026-08-07T00:00:00Z",
    }
    (tmp_path / "counter_parity_last.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )
    out = load_feature_store_ops_posture(
        rules_path=str(tmp_path),
        redis_url="redis://localhost:6379/0",
    )
    assert out["ops_ready"] is True
    assert out["offline_parity"]["dual_diff_proven"] is True
    assert out["blockers"] == []
    # Still never Feast/Flink product claim
    assert out["feast_class_claim_allowed"] is False
    assert out["streaming_flink_claim_allowed"] is False
