"""Gate (Prompt 200): observation promotion publishes NATS feedback with matched entity ids."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_SRC_RULE = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_RULE, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rule_engine.main import create_app  # noqa: E402
from rule_engine.promotion_feedback import build_promotion_feedback_payload  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


def test_build_promotion_feedback_payload_shape() -> None:
    payload = build_promotion_feedback_payload(
        {"id": "shadow_rule_902", "metadata": {"promoted_from": "observation"}},
        entity_ids=["ent-a", "ent-b"],
        rule_version=3,
    )
    assert payload["event"] == "rule_promoted_to_production"
    assert payload["rule_id"] == "shadow_rule_902"
    assert payload["entity_ids"] == ["ent-a", "ent-b"]
    assert payload["entity_count"] == 2
    assert payload["rule_version"] == 3


def test_rules_deploy_observation_promotion_publishes_nats(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "promo_gate.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("RULE_ENGINE_DATABASE_URL", url)
    monkeypatch.setenv("NATS_URL", "nats://test.invalid:4222")

    mock_publish = AsyncMock(
        return_value={
            "ok": True,
            "nats_subject": "tarka.hypothesis.promoted",
            "rule_id": "shadow_rule_902",
            "entity_ids": ["user-x"],
            "entity_count": 1,
        },
    )

    rule = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa9",
        "name": "promoted_shadow_rule",
        "root_node": {
            "field": {"field": "amount"},
            "operator": "GT",
            "value": 10.0,
        },
        "action": "BLOCK",
        "priority": 1,
        "metadata": {"promoted_from": "observation", "mode": "active"},
    }

    with patch(
        "rule_engine.promotion_feedback.emit_observation_promotion_feedback",
        mock_publish,
    ):
        app = create_app()
        with TestClient(app) as client:
            r = client.post("/v1/rules/deploy", json={"rules": [rule]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    assert body["promotion_feedback"]
    assert body["promotion_feedback"][0]["entity_count"] == 1
    mock_publish.assert_awaited_once()
