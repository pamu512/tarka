"""FastAPI rule sidecar: ``POST /v1/evaluate``."""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

import pytest

_SRC_RULE = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_RULE, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rule_engine.ast_schemas import (  # noqa: E402
    Action,
    AndNode,
    ConditionNode,
    FieldRef,
    Operator,
    Rule,
)
from rule_engine.main import create_app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


def test_gate_v1_rules_reload_then_evaluate_uses_new_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate (service): reload API refreshes ``app.state.ruleset`` from ``load_active_ruleset``."""

    allow_only = Rule(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-000000000001"),
        name="never_matches_high_threshold",
        root_node=ConditionNode(
            field=FieldRef(field="amount"),
            operator=Operator.GT,
            value=999_999.0,
        ),
        action=Action.BLOCK,
        priority=1,
    )
    block_low = Rule(
        id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-000000000002"),
        name="block_positive_amount",
        root_node=ConditionNode(
            field=FieldRef(field="amount"),
            operator=Operator.GT,
            value=0.0,
        ),
        action=Action.BLOCK,
        priority=1,
    )
    loads = iter([(allow_only,), (block_low,)])

    def _fake_load() -> tuple[Rule, ...]:
        return next(loads)

    monkeypatch.setattr("rule_engine.main.load_active_ruleset", _fake_load)
    app = create_app()
    body = {
        "entity_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "amount": 10.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        first = client.post("/v1/evaluate", json=body)
        assert first.status_code == 200
        assert first.json().get("graph_context_fail_open") is False
        assert first.json()["actions"] == []
        rel = client.post("/v1/rules/reload")
        assert rel.status_code == 200
        second = client.post("/v1/evaluate", json=body)
    assert second.status_code == 200
    assert second.json().get("graph_context_fail_open") is False
    assert second.json()["actions"] == ["BLOCK"]
    assert second.json()["blocking_rule_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-000000000002"


def test_v1_rules_reload_returns_count() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/v1/rules/reload")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert isinstance(data.get("count"), int)


def test_health_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_evaluate_returns_shadow_review_when_amount_exceeds_demo_threshold() -> None:
    app = create_app()
    body = {
        "entity_id": "77777777-7777-7777-7777-777777777777",
        "amount": 150.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "wire"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data.get("graph_context_fail_open") is False
    assert data["actions"] == ["SHADOW_REVIEW"]
    assert data["transaction_id"] == "77777777-7777-7777-7777-777777777777"
    assert data.get("blocking_rule_id") is None
    assert isinstance(data.get("evaluation_trace"), list)
    assert len(data["evaluation_trace"]) >= 2


def test_v1_evaluate_returns_block_when_stress_block_lane_marker_present() -> None:
    app = create_app()
    body = {
        "entity_id": "66666666-6666-6666-6666-666666666666",
        "amount": 250.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"lane": "STRESS_BLOCK_LANE"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data.get("graph_context_fail_open") is False
    assert data["actions"] == ["BLOCK"]
    assert data["transaction_id"] == "66666666-6666-6666-6666-666666666666"
    assert data["blocking_rule_id"] == "00000000-0000-0000-0000-00000000c0de"
    assert isinstance(data.get("evaluation_trace"), list)
    assert any(
        row.get("rule_id") == "00000000-0000-0000-0000-00000000c0de" and row.get("matched") is True
        for row in data["evaluation_trace"]
    )


def test_v1_evaluate_graph_linked_blocked_rule_triggers_block_and_logs_graph_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Gate: amount > 100 AND graph_linked_to_blocked_count > 0 ⇒ BLOCK; graph probe is invoked and logged."""

    class _MockGraphProv:
        async def fetch_graph_context(self, transaction):  # noqa: ANN001
            _ = transaction
            return {"graph_linked_to_blocked_count": 1}

    rule_pk = uuid.uuid4()
    txn_id = uuid.uuid4()
    graph_rule = Rule(
        id=rule_pk,
        name="graph_amount_block",
        root_node=AndNode(
            children=[
                ConditionNode(
                    field=FieldRef(field="amount"),
                    operator=Operator.GT,
                    value=100.0,
                ),
                ConditionNode(
                    field=FieldRef(field="graph_linked_to_blocked_count"),
                    operator=Operator.GT,
                    value=0,
                ),
            ],
        ),
        action=Action.BLOCK,
        priority=1,
    )
    app = create_app(graph_context_provider=_MockGraphProv())
    body = {
        "entity_id": str(txn_id),
        "amount": 150.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"user_id": "victim-user", "ip": "203.0.113.9"},
    }
    caplog.set_level(logging.INFO, logger="rule_engine.main")
    with TestClient(app) as client:
        client.app.state.ruleset = (graph_rule,)
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data.get("graph_context_fail_open") is False
    assert data["actions"] == ["BLOCK"]
    assert data["blocking_rule_id"] == str(rule_pk)
    msgs = " ".join(r.message for r in caplog.records)
    assert "rule_engine_graph_context" in msgs
    assert "graph_linked_to_blocked_count=1" in msgs


def test_v1_evaluate_returns_empty_actions_when_demo_rule_does_not_match() -> None:
    app = create_app()
    body = {
        "entity_id": "88888888-8888-8888-8888-888888888888",
        "amount": 50.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    body = response.json()
    assert body.get("graph_context_fail_open") is False
    assert body["actions"] == []
    assert body.get("blocking_rule_id") is None
    assert isinstance(body.get("evaluation_trace"), list)
    assert len(body["evaluation_trace"]) == 2
