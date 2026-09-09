"""Feature-store ops posture — Feast/Flink claims stay fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

from decision_api.feature_store_posture import (
    dual_diff_proven,
    load_feature_store_ops_posture,
)

_REPO = Path(__file__).resolve().parents[3]
_CLAIM_LOCK = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"
_POSTURE = _REPO / "docs" / "contracts" / "feature-store-posture-v1.md"
_FLOWS = _REPO / "docs" / "docs" / "guides" / "feature-data-flows.md"


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


def test_feast_class_claim_false_when_feature_store_url_set(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.example")
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
    assert out["feast_class_claim_allowed"] is False
    assert out["streaming_flink_claim_allowed"] is False


def test_claim_lock_fs_posture_row():
    lock = _CLAIM_LOCK.read_text(encoding="utf-8")
    assert "FEATURE_STORE_URL" in lock
    assert "L2 off" in lock
    assert "Redis L1" in lock
    assert "production online FS" in lock
    assert "Feast-class" in lock
    assert "feature-store-posture-v1.md" in lock
    posture = _POSTURE.read_text(encoding="utf-8")
    assert "Not a production online FS" in posture
    assert "FEATURE_STORE_URL" in posture
    assert "Empty = off" in posture
    assert "feast_class_claim_allowed" in posture
    assert "false" in posture.lower()


def test_feature_data_flows_states_l1_not_production_fs():
    text = _FLOWS.read_text(encoding="utf-8")
    assert "FEATURE_STORE_URL" in text
    assert "L2 off" in text or "L2 is off" in text
    assert "production online FS" in text or "production online feature store" in text
    assert "feast_class_claim_allowed" in text
    assert "no L2 writes" in text or "writer no-op" in text
    assert "backfill" in text.lower()
    assert "writer" in text.lower()
    lock = _CLAIM_LOCK.read_text(encoding="utf-8")
    assert "no L2 writes" in lock or "writers" in lock.lower()
