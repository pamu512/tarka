"""Wave 6: rule hit telemetry file durability."""

from __future__ import annotations

import json

from decision_api import json_rules


def test_rule_telemetry_flushes_to_file(tmp_path, monkeypatch):
    path = tmp_path / "rule_hit_telemetry.json"
    monkeypatch.setenv("RULE_TELEMETRY_PATH", str(path))
    # reset module state for isolation
    json_rules._rule_hit_counts.clear()
    json_rules._telemetry_dirty = 0
    json_rules._telemetry_file_loaded = False

    json_rules.record_rule_hit("pack.json", "r1", "rule")
    snap = json_rules.get_rule_hit_telemetry()
    assert snap["durability"] == "file"
    assert snap["total_hits"] >= 1
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_id"] == "tarka.rule_hit_telemetry/v1"
    assert any("r1" in k for k in data["counts"])
