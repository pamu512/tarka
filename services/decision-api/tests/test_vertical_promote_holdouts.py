"""Track P — labeled fixture holdouts gate promote; typology by_vertical."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from decision_api.backtest_promote_gate import fixture_holdout_promote_gate
from decision_api.typology_ops import load_typology_ops_posture
from decision_api.vertical_promote_registry import (
    evaluate_holdout_for_pack,
    holdout_dir,
    load_all_vertical_promote_posture,
)


def test_holdout_files_exist_and_sized():
    for name in ("marketplace", "food_delivery", "e_hailing"):
        path = holdout_dir() / f"{name}.jsonl"
        assert path.is_file(), path
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) >= 100
        assert {int(r["y"]) for r in rows} == {0, 1}


def test_priority_verticals_promote_on_fixture_holdout():
    body = load_all_vertical_promote_posture()
    assert body["schema_id"] == "tarka.vertical_promote_ops/v1"
    assert body["promote_live_claim_allowed"] is False
    assert body["all_priority_fixture_ok"] is True
    for pack in body["packs"]:
        assert pack["promote_fixture_claim_allowed"] is True
        assert pack["promote_live_claim_allowed"] is False
        assert pack["metrics"]["f1_score"] >= 0.5
        assert pack["rows"] >= 100


def test_promote_blocked_when_f1_fails():
    # Invert labels → pack fires on y=0 → precision collapse
    bad_rows = [
        {"id": "bad-pos", "y": 0, "features": {"cross_role_same_device": True, "lifecycle_risk_high": True, "ftid_refund_hold": True, "seller_gmv_30d": 50000, "kyb_unverified": True, "amount": 200, "account_age_days": 2}},
        {"id": "bad-neg", "y": 1, "features": {"amount": 10, "account_age_days": 400, "transaction_count_24h": 1}},
    ] * 60
    with patch(
        "decision_api.vertical_promote_registry.load_holdout_rows",
        return_value=bad_rows,
    ):
        with patch(
            "decision_api.vertical_promote_registry.holdout_path",
            return_value=Path("/tmp/fake_marketplace.jsonl"),
        ):
            # force file "exists" for fixture gate via evaluate path
            result = evaluate_holdout_for_pack("marketplace")
    assert result["promote_fixture_claim_allowed"] is False
    assert result["promote_live_claim_allowed"] is False
    assert result["blockers"]


def test_fixture_holdout_gate_binds_when_file_present():
    gate = fixture_holdout_promote_gate(vertical="marketplace")
    assert gate["waived"] is False
    assert gate["promote_live_claim_allowed"] is False
    assert gate["promote_fixture_claim_allowed"] is True
    assert gate["promote_allowed"] is True


def test_typology_ops_by_vertical_block():
    posture = load_typology_ops_posture()
    assert "by_vertical" in posture
    by_v = posture["by_vertical"]
    assert "marketplace" in by_v
    assert "e_hailing" in by_v
    assert any(tid.startswith("marketplace_") for tid in by_v["marketplace"])
    assert "e_hailing_self_ride" in by_v["e_hailing"]

    hist = {
        "driver_typology_counts": {
            "marketplace_lifecycle_abuse": 3,
            "e_hailing_self_ride": 2,
            "velocity_abuse": 9,
        }
    }
    filtered = load_typology_ops_posture(
        audit_breach_histogram=hist, vertical="marketplace"
    )
    drivers = filtered["audit_breach_histogram"]["driver_typology_counts"]
    assert "marketplace_lifecycle_abuse" in drivers
    assert "e_hailing_self_ride" not in drivers
