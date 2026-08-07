"""Diligence readiness aggregate — closed-loop claims stay fail-closed."""

from __future__ import annotations

from decision_api.diligence_readiness import load_diligence_readiness


def test_oss_default_closed_loop_false(tmp_path):
    out = load_diligence_readiness(rules_path=str(tmp_path), redis_url="")
    assert out["schema_id"] == "tarka.diligence_readiness/v1"
    assert out["soc2_attestation"] is False
    assert out["closed_loop_claims_ready"] is False
    assert "l2_" in " ".join(out["blockers"]) or any(
        b.startswith("l2_") for b in out["blockers"]
    )
    assert any(b.startswith("l3_") for b in out["blockers"])
    assert "loyalty_feeds_not_proven" in out["blockers"]
    assert out["gates"]["l2_partner_fusion"]["live_claim_allowed"] is False
    assert out["gates"]["l3_ops_ledger"]["claim_allowed"] is False
    assert out["doc_index"]["complete"] is True
    assert out["diligence_pack_ready"] is True
