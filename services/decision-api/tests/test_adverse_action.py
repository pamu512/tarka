from decision_api import adverse_action as aa


def test_adverse_empty():
    assert aa.adverse_action_codes_for_hits([]) == []


def test_adverse_unmapped_fallback():
    assert aa.adverse_action_codes_for_hits(["unknown_hit_xyz"]) == ["G99: Internal Policy"]


def test_adverse_respects_max_four_and_order():
    hits = [
        "velocity_high",
        "graph_network_risk",
        "blacklist_block",
        "device_intelligence_risk",
        "external_signal_risk",
        "consortium_shared_signal",
    ]
    out = aa.adverse_action_codes_for_hits(hits)
    assert len(out) == 4
    assert out[0].startswith("V03")


def test_adverse_dedupes_same_code():
    out = aa.adverse_action_codes_for_hits(["velocity_high", "velocity_high"])
    assert out == ["V01: Excessive recent activity"]
