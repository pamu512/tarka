import json

import pytest

from decision_api.live_rule_slip import (
    build_retire_pack,
    build_successor_pack,
    existing_slip_slot,
    find_live_rule,
    live_rule_slip,
    mix_value,
    resolve_y,
    sanitize_rule_id,
    successor_mix,
    write_slip_pack,
)


def _row(i, *, hits=(), y=None, event="payment", geo="US", decision="allow", entity=None):
    return {
        "trace_id": f"t{i}",
        "entity_id": entity or f"e{i}",
        "event_type": event,
        "decision": decision,
        "rule_hits": list(hits),
        "payload_snapshot": {"payload": {"geo_country": geo}},
        "y_label": y or "",
    }


def _half(start, n, **kw):
    return [_row(start + i, **kw) for i in range(n)]


def test_window_underpowered_no_rules():
    rows = _half(0, 40) + _half(40, 40)
    out = live_rule_slip(rows, by_trace={}, by_entity={}, fp_cap=0.4)
    assert out["window"] == "underpowered"
    assert out["rules"] == []


def test_fire_rate_only_underpowered_hypothesis():
    prior = _half(0, 50, hits=())
    current = _half(50, 40, hits=()) + _half(90, 10, hits=["r1"], decision="deny")
    # newest-first: current half is the list prefix (same as the 500-row query)
    out = live_rule_slip(current + prior, by_trace={}, by_entity={}, fp_cap=0.4)
    assert out["window"] == "ok"
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert "fire_rate" in row["triggers"]
    assert row["hypothesis"] == "underpowered"
    assert row["miss_is_not_recall"] is True
    assert row["parked_draft"] is None


def test_mix_and_h2_successor_not_h1():
    prior = _half(0, 50, hits=["r1"], geo="US")
    misses = _half(50, 5, hits=(), y="1", geo="DE", decision="deny")
    hits = _half(55, 45, hits=["r1"], geo="DE")
    by_trace = {f"t{i}": "1" for i in range(50, 55)}
    out = live_rule_slip(
        misses + hits + prior, by_trace=by_trace, by_entity={}, fp_cap=0.4
    )
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert "mix" in row["triggers"]
    assert row["hypothesis"] == "successor"
    assert row["miss_count"] >= 5


def test_h1_retire_not_h2():
    # 50+50 window; r1 fires at a new rate; 5 labeled FP hits; no leftover-fraud misses
    prior = _half(0, 50, hits=())
    labeled = [
        _row(50 + i, hits=["r1"], y="0", decision="deny", geo="US") for i in range(5)
    ]
    current_rest = _half(55, 45, hits=["r1"], geo="US")
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    out = live_rule_slip(
        labeled + current_rest + prior, by_trace=by_trace, by_entity={}, fp_cap=0.4
    )
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert row["hypothesis"] == "retire"
    assert row["fp_rate"] > 0.4


def test_both_hypotheses_ambiguous():
    prior = _half(0, 50, hits=["r1"], geo="US")
    fps = [_row(50 + i, hits=["r1"], y="0", decision="deny", geo="DE") for i in range(5)]
    misses = [_row(55 + i, hits=(), y="1", geo="DE", decision="deny") for i in range(5)]
    rest = _half(60, 40, hits=["r1"], geo="DE")
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    by_trace.update({f"t{55 + i}": "1" for i in range(5)})
    out = live_rule_slip(
        fps + misses + rest + prior, by_trace=by_trace, by_entity={}, fp_cap=0.4
    )
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert row["hypothesis"] == "ambiguous"


def test_resolve_y_trace_then_entity_ignores_proxy():
    row = _row(1, entity="e1")
    assert resolve_y(row, {"t1": "1"}, {}) == "1"
    assert resolve_y(row, {}, {"e1": "0"}) == "0"
    assert resolve_y(row, {"t1": "proxy"}, {"e1": "1"}) == "1"
    assert mix_value(row, "geo_country") == "US"


def test_sanitize_and_slot():
    assert sanitize_rule_id("r1/foo") == "r1_foo"
    assert existing_slip_slot(
        "r1",
        [{"name": "slip_retire_r1", "mode": "shadow", "evidence": {"live_rule_id": "r1"}}],
    ) == "slip_retire_r1"


def test_clobber_name_and_slot():
    from decision_api.live_rule_slip import slip_draft_would_clobber

    assert slip_draft_would_clobber("slip_retire_r1", None, [])
    assert slip_draft_would_clobber(
        "scout_x",
        {"live_rule_id": "r1"},
        [{"name": "slip_retire_r1", "mode": "shadow", "evidence": {"live_rule_id": "r1"}}],
    )
    assert not slip_draft_would_clobber("scout_x", {}, [])


def test_find_live_and_retire_shape():
    packs = [{"_source_file": "a.json", "mode": "active", "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gt", "value": 10}], "score_delta": 20}]}]
    found = find_live_rule("r1", packs)
    assert found["when"][0]["field"] == "amount"
    pack = build_retire_pack("r1", found["when"], fp_rate=0.8, triggers=["fire_rate"])
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is False
    assert pack["authored_by"] == "slip_critic"
    assert pack["rules"][0]["id"] == "r1"
    assert pack["rules"][0]["score_delta"] == 5
    assert pack["evidence"]["slip_kind"] == "retire"
    assert pack["evidence"]["miss_is_not_recall"] is True


def test_successor_legal_when_and_skip_unknown_field():
    pack = build_successor_pack("r1", "geo_country", "DE", miss_count=5, triggers=["mix"])
    assert pack["rules"][0]["score_delta"] == 15
    assert pack["rules"][0]["when"] == [{"field": "geo_country", "op": "eq", "value": "DE"}]
    assert pack["is_ai_authored"] is False
    assert build_successor_pack("r1", "not_a_field", "x", miss_count=5, triggers=["mix"]) is None


def test_write_slip_pack_roundtrip(tmp_path, monkeypatch):
    from decision_api.config import settings

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    pack = build_retire_pack("r1", [{"field": "amount", "op": "gt", "value": 1}], fp_rate=0.9, triggers=["fire_rate"])
    name = write_slip_pack(pack)
    assert (tmp_path / name).is_file()
    assert name.startswith("slip_retire_")


def test_successor_mix_dominant_geo_on_misses():
    current = _half(0, 5, hits=(), y="1", geo="DE", decision="deny")
    by_trace = {f"t{i}": "1" for i in range(5)}
    assert successor_mix(current, "r1", by_trace, {}) == ("geo_country", "DE")


@pytest.mark.asyncio
async def test_park_xor_and_dedup(tmp_path, monkeypatch):
    from decision_api.live_rule_slip import maybe_park_live_rule_slip
    from decision_api.config import settings
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "live.json").write_text(
        json.dumps({
            "version": 1, "name": "live", "mode": "active",
            "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gt", "value": 1}], "score_delta": 20}],
        }),
        encoding="utf-8",
    )
    from decision_api.json_rules import load_rules
    load_rules()
    prior = _half(0, 50, hits=())
    labeled = [_row(50 + i, hits=["r1"], y="0", decision="deny") for i in range(5)]
    rest = _half(55, 45, hits=["r1"])
    rows = labeled + rest + prior
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    monkeypatch.setattr(
        "decision_api.live_rule_slip.load_y_maps",
        lambda tid: (by_trace, {}),
    )
    first = await maybe_park_live_rule_slip("demo", rows=rows)
    assert first["parked"]
    second = await maybe_park_live_rule_slip("demo", rows=rows)
    assert second["parked"] == []
    assert "already_parked" in {s["reason"] for s in second["skipped"]}


@pytest.mark.asyncio
async def test_park_skips_ambiguous(tmp_path, monkeypatch):
    from decision_api.live_rule_slip import maybe_park_live_rule_slip
    from decision_api.config import settings
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "live.json").write_text(
        json.dumps({
            "version": 1, "name": "live", "mode": "active",
            "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gt", "value": 1}], "score_delta": 20}],
        }),
        encoding="utf-8",
    )
    from decision_api.json_rules import load_rules
    load_rules()
    prior = _half(0, 50, hits=["r1"], geo="US")
    fps = [_row(50 + i, hits=["r1"], y="0", decision="deny", geo="DE") for i in range(5)]
    misses = [_row(55 + i, hits=(), y="1", geo="DE", decision="deny") for i in range(5)]
    rest = _half(60, 40, hits=["r1"], geo="DE")
    rows = fps + misses + rest + prior
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    by_trace.update({f"t{55 + i}": "1" for i in range(5)})
    monkeypatch.setattr(
        "decision_api.live_rule_slip.load_y_maps",
        lambda tid: (by_trace, {}),
    )
    out = await maybe_park_live_rule_slip("demo", rows=rows)
    assert out["parked"] == []
    assert "ambiguous" in {s["reason"] for s in out["skipped"]}
