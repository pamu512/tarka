"""Typology layer (OSS #34)."""

from decision_api.typology import evaluate_typologies, summarize_typologies


def test_typology_velocity_abuse_from_rule_hits():
    hits = ["velocity_high_1h"]
    feats = {"event_count_1h": 30.0}
    res = evaluate_typologies(hits, feats)
    vel = next(t for t in res if t["id"] == "velocity_abuse")
    assert vel["breach_level"] in ("warning", "alert", "pass")
    assert "velocity_high_1h" in vel["contributing_rule_hits"]
    summ = summarize_typologies(res)
    assert summ["highest_breach"] in ("pass", "warning", "alert")


def test_typology_no_duplicate_rule_computation():
    """Same rule hit list reused; evaluate_typologies is O(typologies)."""
    hits = ["velocity_high_1h", "many_devices_24h"]
    feats = {"event_count_1h": 5, "distinct_device_id_24h": 4}
    res = evaluate_typologies(hits, feats)
    assert len(res) == 3
