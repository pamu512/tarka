"""Batch regression: evaluate_json_rules outcomes from fixtures/test_payloads.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from decision_api import json_rules
from decision_api.config import settings
from decision_api.json_rules import evaluate_json_rules

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PAYLOADS_PATH = _FIXTURES / "test_payloads.json"
_DEFAULT_PACK_PATH = _FIXTURES / "test_rules_batch_pack.json"


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"missing fixture: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_pack(raw: dict[str, Any]) -> dict[str, Any]:
    pack = dict(raw)
    pack.setdefault("version", 1)
    pack.setdefault("mode", "active")
    pack.setdefault("_source_file", "test_rules_batch_pack.json")
    pack.setdefault("rules", [])
    pack.setdefault("tag_rules", [])
    return pack


def _action_from_score(score: float) -> str:
    if score >= settings.deny_threshold:
        return "deny"
    if score >= settings.review_threshold:
        return "review"
    return "allow"


def _evaluate_case(
    case: dict[str, Any],
    default_pack: dict[str, Any],
) -> dict[str, Any]:
    pack = _normalize_pack(case.get("rule_pack") or default_pack)
    json_rules._cached_packs = [pack]
    base_score = float(case.get("base_score", 10.0))
    features = dict(case.get("features") or {})
    redis_tags = list(case.get("redis_tags") or [])
    signal_tags = list(case.get("signal_tags") or [])
    tenant_id = str(case.get("tenant_id") or "batch-test-tenant")
    entity_id = str(case.get("entity_id") or "batch-test-entity")

    hits, tags, score_delta, _pack_files = evaluate_json_rules(
        features,
        redis_tags,
        tenant_id=tenant_id,
        entity_id=entity_id,
        evaluation_mode="simulation",
        signal_tags=signal_tags,
    )
    score = base_score + float(score_delta)
    return {
        "rule_hits": hits,
        "tags": tags,
        "score_delta": float(score_delta),
        "score": score,
        "action": _action_from_score(score),
    }


def _load_batch_cases() -> list[dict[str, Any]]:
    raw = _load_json(_PAYLOADS_PATH)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("payloads"), list):
        return raw["payloads"]
    raise ValueError(f"{_PAYLOADS_PATH}: expected JSON array or {{payloads: [...]}}")


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("name") or case.get("id") or "unnamed")


_BATCH_CASES = _load_batch_cases()
_DEFAULT_PACK = _normalize_pack(_load_json(_DEFAULT_PACK_PATH))


@pytest.fixture(autouse=True)
def _stub_rule_telemetry():
    json_rules.record_rule_hit = lambda *args, **kwargs: None  # type: ignore[method-assign]
    yield


@pytest.fixture(autouse=True)
def _reset_cached_packs():
    yield
    json_rules._cached_packs = []


@pytest.mark.parametrize("case", _BATCH_CASES, ids=[_case_id(c) for c in _BATCH_CASES])
def test_rules_batch_payload(case: dict[str, Any]) -> None:
    expected = case.get("expected")
    assert isinstance(expected, dict), f"{_case_id(case)}: missing expected object"

    actual = _evaluate_case(case, _DEFAULT_PACK)
    name = _case_id(case)

    assert actual["score_delta"] == pytest.approx(float(expected["score_delta"])), (
        f"{name}: score_delta expected {expected['score_delta']!r}, got {actual['score_delta']!r}"
    )
    assert actual["score"] == pytest.approx(float(expected["score"])), (
        f"{name}: score expected {expected['score']!r}, got {actual['score']!r}"
    )
    assert actual["action"] == expected["action"], (
        f"{name}: action expected {expected['action']!r}, got {actual['action']!r}"
    )

    if "rule_hits" in expected:
        assert actual["rule_hits"] == expected["rule_hits"], (
            f"{name}: rule_hits expected {expected['rule_hits']!r}, got {actual['rule_hits']!r}"
        )
    if "tags" in expected:
        assert actual["tags"] == expected["tags"], (
            f"{name}: tags expected {expected['tags']!r}, got {actual['tags']!r}"
        )
