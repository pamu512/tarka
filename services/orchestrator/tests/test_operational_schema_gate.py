"""Tests for core :mod:`orchestrator.schemas.operational` contract."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_core_operational_signal_uses_entity_id() -> None:
    from schemas.operational import OperationalSignalCreate, SignalType

    body = OperationalSignalCreate.model_validate(
        {
            "idempotency_key": "cb:core:1",
            "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "signal_type": SignalType.CHARGEBACK_RECEIVED,
            "metadata": {
                "amount_cents": 9900,
                "currency": "USD",
                "chargeback_reason_code": "4853",
                "card_network": "VISA",
            },
        },
    )
    assert body.entity_id == UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert body.signal_type == SignalType.CHARGEBACK_RECEIVED


def test_core_operational_signal_rejects_mismatched_metadata() -> None:
    from schemas.operational import OperationalSignalCreate, SignalType

    with pytest.raises(ValidationError):
        OperationalSignalCreate.model_validate(
            {
                "idempotency_key": "refund:core:1",
                "entity_id": str(UUID(int=1)),
                "signal_type": SignalType.REFUND_ISSUED,
                "metadata": {
                    "amount_cents": 100,
                    "currency": "USD",
                    "chargeback_reason_code": "4853",
                    "card_network": "VISA",
                },
            },
        )
