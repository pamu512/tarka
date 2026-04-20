from decision_api.tags import derive_contextual_tags


def test_derive_contextual_tags_includes_velocity_geo_graph_and_external():
    tags = derive_contextual_tags(
        features={
            "event_count_5m": 6,
            "event_count_1h": 20,
            "event_count_24h": 30,
            "geo_ip_mismatch": True,
        },
        signal_tags=["sdk:shared_device", "sdk:geo_tz_mismatch"],
        graph_risk={"risk_score": 81, "risk_factors": ["shared_devices_4", "large_community_9"]},
        external_signal_meta={"risk_score": 72, "providers": ["scameter"]},
    )
    assert "velocity_high_5m" in tags
    assert "velocity_high_1h" in tags
    assert "geo_ip_mismatch" in tags
    assert "geo_tz_mismatch" in tags
    assert "shared_device_detected" in tags
    assert "graph_risk_high" in tags
    assert "ring_shared_device" in tags
    assert "external_signal:scameter" in tags
