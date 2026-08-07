"""P0-L2: LIVE|WAIVED status parse."""

from __future__ import annotations

from decision_api.partner_fusion_status import load_partner_fusion_status, parse_live_status_line


def test_parse_waived():
    out = parse_live_status_line(
        "WAIVED — reason: no live vendor credentials in environment"
    )
    assert out["status"] == "WAIVED"
    assert "no live vendor" in out["reason"]
    assert out["promote_live_claim_allowed"] is False


def test_parse_live():
    assert parse_live_status_line("LIVE")["status"] == "LIVE"


def test_load_repo_status_is_waived():
    body = load_partner_fusion_status()
    assert body["schema_id"] == "tarka.partner_fusion_status/v1"
    assert body["status"] in {"WAIVED", "LIVE", "MISSING", "INVALID"}
    assert "opensanctions" in body
    # Current committed posture is WAIVED without forged pins
    if body["status"] == "WAIVED":
        assert body["promote_live_claim_allowed"] is False
