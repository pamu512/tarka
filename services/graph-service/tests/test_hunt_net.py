from datetime import UTC, datetime

from graph_service.hunt_net import apply_hunt_net, clamp_lookback_days


def test_clamp_lookback_days():
    assert clamp_lookback_days(None) is None
    assert clamp_lookback_days("90") == 90
    assert clamp_lookback_days(99999) == 2555


def test_apply_hunt_net_drops_old_login_keeps_device_and_undated():
    now = datetime(2026, 9, 1, tzinfo=UTC)
    data = {
        "nodes": [
            {"id": "buyer", "labels": ["Person"], "properties": {}},
            {"id": "dev-1", "labels": ["Device"], "properties": {}},
            {
                "id": "login:old",
                "labels": ["Login"],
                "properties": {"created_at": "2025-01-01T00:00:00Z"},
            },
            {"id": "login:undated", "labels": ["Login"], "properties": {}},
        ],
        "edges": [
            {"from_id": "buyer", "to_id": "dev-1", "type": "USED_DEVICE"},
            {"from_id": "buyer", "to_id": "login:old", "type": "PERFORMED_LOGIN"},
            {"from_id": "buyer", "to_id": "login:undated", "type": "PERFORMED_LOGIN"},
        ],
    }
    out = apply_hunt_net(data, seed_id="buyer", lookback_days=90, types=None, now=now)
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {"buyer", "dev-1", "login:undated"}


def test_apply_hunt_net_types_keep_seed():
    data = {
        "nodes": [
            {"id": "buyer", "labels": ["Person"], "properties": {}},
            {"id": "dev-1", "labels": ["Device"], "properties": {}},
            {"id": "pay-1", "labels": ["Payment"], "properties": {}},
        ],
        "edges": [
            {"from_id": "buyer", "to_id": "dev-1", "type": "USED_DEVICE"},
            {"from_id": "buyer", "to_id": "pay-1", "type": "MADE_PAYMENT"},
        ],
    }
    out = apply_hunt_net(data, seed_id="buyer", lookback_days=None, types=["Device"])
    assert {n["id"] for n in out["nodes"]} == {"buyer", "dev-1"}
