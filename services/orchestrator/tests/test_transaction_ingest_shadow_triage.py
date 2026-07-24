"""Unit tests: expanded Shadow sync trigger + action modulation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from transaction_ingest import (  # noqa: E402
    graph_indicators_nonzero,
    modulate_actions_with_shadow_advice,
    should_invoke_shadow_synchronously,
    velocity_indicators_nonzero,
)


def _tx(**meta: object) -> TransactionSchema:
    return TransactionSchema(
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=88.0,
        timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        metadata=dict(meta),
    )


def test_should_invoke_shadow_for_flag_with_velocity_metadata() -> None:
    tx = _tx(event_count_5m=3)
    rule_data = {"actions": ["FLAG"], "evaluation_trace": []}
    assert velocity_indicators_nonzero(rule_data, tx) is True
    assert should_invoke_shadow_synchronously(["FLAG"], rule_data, tx) is True


def test_should_not_invoke_shadow_for_flag_without_indicators() -> None:
    tx = _tx(channel="wire")
    rule_data = {"actions": ["FLAG"], "evaluation_trace": []}
    assert should_invoke_shadow_synchronously(["FLAG"], rule_data, tx) is False


def test_should_invoke_shadow_for_flag_with_graph_signals() -> None:
    tx = _tx(user_id="u1")
    rule_data = {"actions": ["FLAG"], "evaluation_trace": []}
    signals = {
        "IP_VELOCITY": {"distinct_users_last_2h": 6, "spike": True, "score": 1.2},
    }
    assert graph_indicators_nonzero(rule_data, tx, signals) is True
    assert (
        should_invoke_shadow_synchronously(["FLAG"], rule_data, tx, graph_signals=signals) is True
    )


def test_modulate_actions_never_clears_flag_on_low_shadow_risk() -> None:
    out = modulate_actions_with_shadow_advice(
        ["FLAG"],
        {
            "risk_score": 10.0,
            "is_fraud": False,
            "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "reasoning": [],
            "confidence_metrics": {},
        },
    )
    assert out == ["FLAG"]


def test_modulate_actions_preserves_deterministic_actions() -> None:
    out = modulate_actions_with_shadow_advice(
        ["FLAG", "SHADOW_REVIEW"],
        {
            "risk_score": 88.0,
            "is_fraud": True,
            "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "reasoning": [],
            "confidence_metrics": {},
        },
    )
    assert out == ["FLAG", "SHADOW_REVIEW"]
