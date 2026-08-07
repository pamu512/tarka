"""C1 loyalty feed-gate honesty."""

from __future__ import annotations

from decision_api.loyalty_feed_posture import (
    claim_allowed_for_economics_status,
    load_loyalty_feed_ops_posture,
    parse_feeds_status_line,
    validate_feed_snapshot,
)


def test_incomplete_never_claim_allowed():
    out = validate_feed_snapshot({"orders": [], "refunds": [], "loyalty_ledger": [], "lifecycle": []})
    assert out["status"] == "feeds_incomplete"
    assert out["claim_allowed"] is False


def test_missing_never_claim_allowed():
    assert validate_feed_snapshot(None)["status"] == "feeds_missing"
    assert validate_feed_snapshot(None)["claim_allowed"] is False


def test_complete_keys_still_not_live_claim():
    snap = {
        "orders": [{"entity_id": "e1"}],
        "refunds": [],
        "loyalty_ledger": [{"entity_id": "e1"}],
        "lifecycle": [{"entity_id": "e1"}],
    }
    out = validate_feed_snapshot(snap)
    assert out["status"] == "feeds_complete"
    # Complete fixture keys ≠ live warehouse claim
    assert out["claim_allowed"] is False


def test_economics_blocking_statuses():
    for s in ("feeds_missing", "feeds_incomplete", "stale", "config_missing"):
        assert claim_allowed_for_economics_status(s) is False
    assert claim_allowed_for_economics_status("ok") is False  # needs FEEDS_READY pin


def test_status_file_not_proven(tmp_path, monkeypatch):
    p = tmp_path / "loyalty-feeds.status"
    p.write_text(
        "FEEDS_NOT_PROVEN — reason: no tenant warehouse feeds in OSS\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TARKA_LOYALTY_FEEDS_STATUS_PATH", str(p))
    monkeypatch.delenv("LOYALTY_ABUSE_URL", raising=False)
    monkeypatch.delenv("LOYALTY_ABUSE_API_KEY", raising=False)
    monkeypatch.delenv("TARKA_LOYALTY_ABUSE_URL", raising=False)
    monkeypatch.delenv("TARKA_LOYALTY_ABUSE_API_KEY", raising=False)
    out = load_loyalty_feed_ops_posture()
    assert out["live_claim_allowed"] is False
    assert "loyalty_bridge_unconfigured" in out["blockers"]
    assert out["feeds_status"]["status"] == "FEEDS_NOT_PROVEN"


def test_feeds_ready_still_needs_bridge(tmp_path, monkeypatch):
    p = tmp_path / "loyalty-feeds.status"
    p.write_text("FEEDS_READY\n", encoding="utf-8")
    monkeypatch.setenv("TARKA_LOYALTY_FEEDS_STATUS_PATH", str(p))
    out = load_loyalty_feed_ops_posture(
        loyalty_abuse_url="http://loyalty",
        loyalty_abuse_api_key="secret",
    )
    assert out["live_claim_allowed"] is True
    assert out["blockers"] == []


def test_parse_status_line():
    assert parse_feeds_status_line("FEEDS_READY")["live_claim_allowed"] is True
    assert parse_feeds_status_line("FEEDS_NOT_PROVEN — reason: x")["live_claim_allowed"] is False
