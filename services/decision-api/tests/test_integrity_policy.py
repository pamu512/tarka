"""Unit tests for integrity policy helpers (no FastAPI)."""

from decision_api.integrity_policy import haversine_km, supplemental_tags_for_integrity, trusted_zone_hit


def test_supplemental_tags_android_emulator():
    tags = supplemental_tags_for_integrity("android", ["sdk:emulator"])
    assert any("integrity" in t for t in tags)


def test_haversine_short_distance():
    # ~0 km for same point
    assert haversine_km(40.7, -74.0, 40.7, -74.0) < 1.0


def test_trusted_zone():
    assert trusted_zone_hit(40.71, -74.01, [{"lat": 40.71, "lon": -74.01, "radius_km": 50}]) is True
