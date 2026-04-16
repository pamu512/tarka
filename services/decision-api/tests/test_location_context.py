"""Session geo merge + consistency tags."""

from decision_api.location_context import merge_session_geo_from_device_and_features


def test_fills_session_from_gps_signals():
    feats = {
        "geo_lat": 40.71,
        "geo_lon": -74.01,
        "geo_source": "browser_gps",
        "geo_ts": "2026-01-01T12:00:00+00:00",
        "ip_geo_lat": 40.72,
        "ip_geo_lon": -74.02,
        "timezone": "America/New_York",
        "ip_geo_timezone": "America/New_York",
    }
    tags = merge_session_geo_from_device_and_features(feats)
    assert feats.get("session_last_lat") == 40.71
    assert feats.get("session_last_lon") == -74.01
    assert "sdk:geo_ip_mismatch" not in tags


def test_geo_ip_mismatch_tag():
    feats = {
        "geo_lat": 51.5,
        "geo_lon": -0.12,
        "geo_source": "browser_gps",
        "geo_ts": "2026-01-01T12:00:00+00:00",
        "ip_geo_lat": 40.71,
        "ip_geo_lon": -74.01,
        "timezone": "Europe/London",
        "ip_geo_timezone": "America/New_York",
    }
    tags = merge_session_geo_from_device_and_features(feats)
    assert "sdk:geo_ip_mismatch" in tags
    assert "sdk:geo_tz_mismatch" in tags


def test_fallback_ip_geo_when_no_gps():
    feats = {"ip_geo_lat": 37.77, "ip_geo_lon": -122.42}
    merge_session_geo_from_device_and_features(feats)
    assert feats.get("session_last_lat") == 37.77
    assert feats.get("session_last_lon") == -122.42
    assert feats.get("geo_source_resolved") == "ip_geolocation"
