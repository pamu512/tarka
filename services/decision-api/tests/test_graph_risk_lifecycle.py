"""Option B+C: enable-shadow requires serve_allowed; train is fixed recipe."""

from __future__ import annotations

import pytest

from decision_api.gnn_loop.lifecycle import (
    SidecarLifecycleError,
    enable_shadow,
    run_train,
)
from decision_api.gnn_loop.train import write_gate_artifact


def test_enable_shadow_409_without_serve_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GNN_LOOP_GATE_PATH", str(tmp_path / "gate.json"))
    write_gate_artifact(
        tmp_path / "gate.json",
        {
            "serve_allowed": False,
            "beats_heuristic": False,
            "baseline": "heuristic_v1",
            "reason": "holdout_did_not_beat_heuristic_v1",
            "model_auc": 0.5,
            "heuristic_auc": 0.6,
            "weights": [],
            "bias": 0.0,
        },
    )
    with pytest.raises(SidecarLifecycleError) as ei:
        enable_shadow("acme", shadow_url="http://127.0.0.1:8091", actor="ana-1")
    assert ei.value.code == "serve_not_allowed"
    assert ei.value.http_status == 409


def test_enable_shadow_ok_when_gate_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GNN_LOOP_GATE_PATH", str(tmp_path / "gate.json"))
    write_gate_artifact(
        tmp_path / "gate.json",
        {
            "serve_allowed": True,
            "beats_heuristic": True,
            "baseline": "heuristic_v1",
            "reason": "ok",
            "model_auc": 0.9,
            "heuristic_auc": 0.6,
            "weights": [0.1],
            "bias": 0.0,
        },
    )
    out = enable_shadow("acme", shadow_url="http://127.0.0.1:8091", actor="ana-1")
    assert out["ok"] is True
    assert out["lifecycle"]["state"] == "shadow"
    assert out["lifecycle"]["shadow_enabled"] is True
    assert out["gnn_claim_allowed"] is False
    assert out["lifecycle"]["live_effect"] == "pack_promote_only"


def test_train_requires_actor(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GNN_LOOP_GATE_PATH", str(tmp_path / "gate.json"))
    with pytest.raises(SidecarLifecycleError) as ei:
        run_train("acme", actor="")
    assert ei.value.code == "actor_required"
