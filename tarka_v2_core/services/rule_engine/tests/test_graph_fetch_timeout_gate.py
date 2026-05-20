"""Gate: graph context probe exceeds budget → fail-open (Redis-only graph signal)."""

from __future__ import annotations

import asyncio
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

from rule_engine.ast_schemas import (
    Action,
    AndNode,
    ConditionNode,
    FieldRef,
    Operator,
    Rule,
)  # noqa: E402
from rule_engine.main import create_app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


class _StallGraphProv:
    async def fetch_graph_context(self, transaction):  # noqa: ANN001
        await asyncio.sleep(10.0)
        return {"graph_linked_to_blocked_count": 99}


def test_graph_fetch_timeout_fail_open_skips_blocked_rule(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RULE_ENGINE_GRAPH_FETCH_TIMEOUT_MS", "80")

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
    app = create_app(graph_context_provider=_StallGraphProv())
    body = {
        "entity_id": str(txn_id),
        "amount": 150.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"user_id": "victim-user", "ip": "203.0.113.9"},
    }
    caplog.set_level(logging.WARNING, logger="rule_engine.main")
    with TestClient(app) as client:
        client.app.state.ruleset = (graph_rule,)
        response = client.post("/v1/evaluate", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data.get("graph_context_fail_open") is True
    assert data["actions"] == []
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "rule_engine_graph_context_fetch_timeout" in msgs
