import json
from pathlib import Path

from ml_scoring.model_registry import ModelRegistry


def _write_version(base: Path, model: str, version: int, meta: dict) -> None:
    vdir = base / model / str(version)
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def test_approve_activate_and_rollback(tmp_path: Path):
    _write_version(tmp_path, "fraud", 1, {"traffic_weight": 100, "active": True, "approved": True})
    _write_version(tmp_path, "fraud", 2, {"traffic_weight": 0, "active": False, "approved": False})

    reg = ModelRegistry(tmp_path)
    reg.scan()

    assert reg.is_approved("fraud", 1) is True
    assert reg.is_approved("fraud", 2) is False
    assert reg.approve_version("fraud", 2, "qa-user", "canary") is True
    assert reg.is_approved("fraud", 2) is True
    assert reg.activate_version("fraud", 2) is True

    rolled_back = reg.rollback_to_previous("fraud")
    assert rolled_back == 1


def test_set_traffic_split_requires_100(tmp_path: Path):
    _write_version(tmp_path, "fraud", 1, {"traffic_weight": 100, "active": True})
    _write_version(tmp_path, "fraud", 2, {"traffic_weight": 0, "active": False})
    reg = ModelRegistry(tmp_path)
    reg.scan()

    assert reg.set_traffic_split("fraud", {1: 90, 2: 10}) is True
    assert reg.set_traffic_split("fraud", {1: 80, 2: 10}) is False


def test_lineage_signature_present(tmp_path: Path):
    _write_version(tmp_path, "fraud", 7, {"traffic_weight": 100, "active": True, "approved": True})
    reg = ModelRegistry(tmp_path)
    reg.scan()
    lineage = reg.lineage_signature("fraud", 7)
    assert lineage is not None
    assert "sha256" in lineage
    assert lineage["signed_payload"]["version"] == 7
