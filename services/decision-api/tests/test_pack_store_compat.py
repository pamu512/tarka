"""Pack store: older v1 packs load; unknown versions fail closed clearly."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

from decision_api.json_rules import (
    get_active_packs_snapshot,
    get_disabled_mode_packs,
    load_rules,
)


def _write_pack(path, *, version=1, extra=None, mode="active"):
    body = {
        "version": version,
        "name": path.stem,
        "mode": mode,
        "rules": [
            {
                "id": "r",
                "when": [{"field": "x", "op": "gte", "value": 0}],
                "tags": ["t"],
                "score_delta": 1,
            }
        ],
        "tag_rules": [],
    }
    if extra:
        body.update(extra)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_older_v1_pack_loads_with_unknown_optional_fields(tmp_path):
    _write_pack(
        tmp_path / "legacy.json",
        extra={"future_optional": True, "canary_percent": 10},
    )
    with patch("decision_api.json_rules.settings") as mock:
        mock.rules_path = str(tmp_path)
        load_rules()
    files = [p.get("_source_file") for p in get_active_packs_snapshot()]
    assert "legacy.json" in files


def test_missing_version_defaults_to_v1_and_loads(tmp_path):
    body = {
        "name": "no-ver",
        "rules": [
            {
                "id": "r",
                "when": [{"field": "x", "op": "gte", "value": 0}],
                "tags": ["t"],
                "score_delta": 1,
            }
        ],
        "tag_rules": [],
    }
    (tmp_path / "no-ver.json").write_text(json.dumps(body), encoding="utf-8")
    with patch("decision_api.json_rules.settings") as mock:
        mock.rules_path = str(tmp_path)
        load_rules()
    files = [p.get("_source_file") for p in get_active_packs_snapshot()]
    assert "no-ver.json" in files


def test_unknown_pack_version_fail_closed_and_logged(tmp_path, caplog):
    _write_pack(tmp_path / "v2.json", version=2)
    _write_pack(tmp_path / "v1.json", version=1)
    with patch("decision_api.json_rules.settings") as mock:
        mock.rules_path = str(tmp_path)
        with caplog.at_level(logging.WARNING, logger="decision_api.json_rules"):
            load_rules()
    files = [p.get("_source_file") for p in get_active_packs_snapshot()]
    assert "v1.json" in files
    assert "v2.json" not in files
    assert any(
        "unsupported pack version" in r.message and "v2.json" in r.message
        for r in caplog.records
    )


def test_disabled_mode_is_not_active(tmp_path):
    _write_pack(tmp_path / "off.json", mode="disabled")
    with patch("decision_api.json_rules.settings") as mock:
        mock.rules_path = str(tmp_path)
        load_rules()
    assert "off.json" not in [
        p.get("_source_file") for p in get_active_packs_snapshot()
    ]
    assert "off.json" in [p.get("_source_file") for p in get_disabled_mode_packs()]
