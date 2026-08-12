"""Graph shared-device shadow pack — relatedness, not geo linker."""

from __future__ import annotations

import json
from pathlib import Path

from decision_api.json_rules import evaluate_json_rules
from decision_api.rule_pack_validation import validate_rule_pack

_PACK_PATH = (
    Path(__file__).resolve().parents[1] / "rules" / "graph_shared_device_v1.json"
)


def test_graph_shared_device_pack_validates():
    data = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    assert data.get("mode") == "shadow"
    assert "not geo linker" in str(data.get("description", "")).lower()
    assert validate_rule_pack(data) == []


def test_shared_device_tag_rules_fire():
    import decision_api.json_rules as mod

    pack = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    pack["_source_file"] = "graph_shared_device_v1.json"
    pack["mode"] = "active"
    mod._cached_packs = [pack]

    hits, tags, delta, _ = evaluate_json_rules(
        {}, ["sdk:shared_device", "velocity:high_1h"]
    )
    assert "shared_device_sdk" in hits
    assert "escalate_shared_device_with_velocity" in hits
    assert "graph:shared_device_elevated" in tags
    assert "escalated:graph_shared_device_velocity" in tags
    assert delta >= 16 + 12
