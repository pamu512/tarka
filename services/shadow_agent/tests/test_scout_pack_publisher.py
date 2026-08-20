"""Tests for scout suggestion → observe (shadow) pack persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# shadow_schemas triggers ingestor import; stub it so we can import
# scout_coordinated_burst without heavy deps.
_sentinel = type(sys)("shadow_schemas")
_sentinel.HypothesisReport = type("HypothesisReport", (), {"model_dump": lambda s, **kw: {}})
sys.modules.setdefault("shadow_schemas", _sentinel)

from scout_pack_publisher import scout_report_to_shadow_pack  # noqa: E402


def _make_suggested_rule(fingerprint_kind="canvas_hash", fingerprint_value="abc123"):
    field = "canvas_hash" if fingerprint_kind == "canvas_hash" else "webgl_vendor"
    short = fingerprint_value.replace(" ", "")[:12]
    return {
        "id": f"scout_{fingerprint_kind}_{short}",
        "when": [{"op": "eq", "field": field, "value": fingerprint_value}],
        "score_delta": 25.0,
        "metadata": {
            "is_shadow": True,
            "source": "scout_coordinated_burst",
            "fingerprint_kind": fingerprint_kind,
        },
    }


def _sample_report(*, fingerprint_kind="canvas_hash", fingerprint_value="abc123") -> dict:
    return {
        "report_id": "rpt-001",
        "strategy": "coordinated_burst",
        "fingerprint_kind": fingerprint_kind,
        "fingerprint_value": fingerprint_value,
        "distinct_account_count": 8,
        "suggested_rule": _make_suggested_rule(
            fingerprint_kind=fingerprint_kind,
            fingerprint_value=fingerprint_value,
        ),
    }


def test_pack_has_shadow_mode():
    pack = scout_report_to_shadow_pack(_sample_report())
    assert pack["mode"] == "shadow"
    assert pack["version"] == 1


def test_pack_has_provenance():
    pack = scout_report_to_shadow_pack(_sample_report())
    assert pack["is_ai_authored"] is True
    assert pack["authored_by"] == "scout_coordinated_burst"
    assert pack["scout_report_id"] == "rpt-001"


def test_pack_contains_suggested_rule():
    report = _sample_report()
    pack = scout_report_to_shadow_pack(report)
    assert len(pack["rules"]) == 1
    rule = pack["rules"][0]
    assert rule["when"][0]["field"] == "canvas_hash"
    assert rule["when"][0]["value"] == "abc123"
    assert rule["metadata"]["is_shadow"] is True
    assert rule["metadata"]["source"] == "scout_coordinated_burst"


def test_pack_name_includes_fingerprint_kind():
    pack = scout_report_to_shadow_pack(_sample_report(fingerprint_kind="webgl_vendor", fingerprint_value="ANGLE"))
    assert "webgl_vendor" in pack["name"]
    assert "ANGLE" in pack["name"]
    assert pack["name"].startswith("Scout:")


def test_missing_suggested_rule_raises():
    with pytest.raises(ValueError, match="missing suggested_rule"):
        scout_report_to_shadow_pack({"report_id": "x"})


def test_pack_serialisable_and_valid_structure():
    pack = scout_report_to_shadow_pack(_sample_report())
    raw = json.dumps(pack)
    loaded = json.loads(raw)
    assert loaded["mode"] == "shadow"
    assert loaded["canary_percent"] is None
    assert loaded["approved_by"] is None


def test_pack_written_to_disk_loadable(tmp_path: Path):
    """Simulate writing a scout pack and loading it like decision-api does."""
    pack = scout_report_to_shadow_pack(_sample_report())
    fpath = tmp_path / "scout_test.json"
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")

    loaded = json.loads(fpath.read_text(encoding="utf-8"))
    assert loaded["mode"] == "shadow"
    assert loaded["is_ai_authored"] is True
    assert len(loaded["rules"]) == 1
