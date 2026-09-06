from pathlib import Path

from baseline_assist import (
    COMPUTED_NAME,
    DEFAULT_WARMUP_24H,
    apply_count_share,
    attach_count_share_from_env,
    resolve_warmup_24h,
)


def test_omit_when_24h_below_warmup():
    feats = {"event_count_1h": 4, "event_count_24h": 9, "amount": 3}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats
    assert feats["amount"] == 3


def test_share_when_warmup_met():
    feats = {"event_count_1h": 4, "event_count_24h": 10}
    apply_count_share(feats, 10)
    assert feats[COMPUTED_NAME] == 0.4


def test_share_clamps_to_unit_interval():
    over = {"event_count_1h": 15, "event_count_24h": 10}
    apply_count_share(over, 10)
    assert over[COMPUTED_NAME] == 1.0
    neg = {"event_count_1h": -2, "event_count_24h": 10}
    apply_count_share(neg, 10)
    assert neg[COMPUTED_NAME] == 0.0


def test_omit_when_24h_zero():
    feats = {"event_count_1h": 0, "event_count_24h": 0}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats


def test_zero_share_when_1h_empty_and_warmup_met():
    feats = {"event_count_24h": 10}
    apply_count_share(feats, 10)
    assert feats[COMPUTED_NAME] == 0.0


def test_omit_when_24h_missing_or_non_numeric():
    feats = {"event_count_1h": 4, "event_count_24h": "x"}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats
    thin = {"event_count_1h": 4}
    apply_count_share(thin, 10)
    assert COMPUTED_NAME not in thin


def test_idempotent_clears_stale_share():
    feats = {"event_count_1h": 1, "event_count_24h": 2, COMPUTED_NAME: 0.99}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats


def test_attach_from_env_uses_warmup(monkeypatch):
    monkeypatch.setenv("TARKA_BASELINE_WARMUP_24H", "2")
    feats = {"event_count_1h": 1, "event_count_24h": 2}
    attach_count_share_from_env(feats)
    assert feats[COMPUTED_NAME] == 0.5
    monkeypatch.setenv("TARKA_BASELINE_WARMUP_24H", "10")
    thin = {"event_count_1h": 1, "event_count_24h": 2}
    attach_count_share_from_env(thin)
    assert COMPUTED_NAME not in thin


def test_pack_gte_false_when_share_omitted():
    from decision_api.json_rules import _match_condition

    feats = {"event_count_1h": 4, "event_count_24h": 4}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats
    assert (
        _match_condition(feats, {"field": COMPUTED_NAME, "op": "gte", "value": 0.5})
        is False
    )


def test_pack_gte_true_when_share_warm():
    from decision_api.json_rules import _match_condition

    feats = {"event_count_1h": 8, "event_count_24h": 10}
    apply_count_share(feats, 10)
    assert (
        _match_condition(feats, {"field": COMPUTED_NAME, "op": "gte", "value": 0.5})
        is True
    )


def test_pipeline_calls_attach_from_env():
    pipeline = Path(__file__).resolve().parents[1] / "src/decision_api/evaluate/pipeline.py"
    text = pipeline.read_text(encoding="utf-8")
    assert "attach_count_share_from_env(features)" in text


def test_resolve_warmup():
    assert resolve_warmup_24h(None) == DEFAULT_WARMUP_24H
    assert resolve_warmup_24h("10") == 10
    assert resolve_warmup_24h("0") == 1
    assert resolve_warmup_24h("-3") == 1
    assert resolve_warmup_24h("nope") == DEFAULT_WARMUP_24H
    assert resolve_warmup_24h("  ") == DEFAULT_WARMUP_24H
