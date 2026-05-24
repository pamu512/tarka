"""Gate: strict operational signal Pydantic schemas."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_chargeback_received_metadata_requires_structured_fields() -> None:
    from orchestrator.schemas.operational_signals import OperationalSignalCreate, SignalType

    body = OperationalSignalCreate.model_validate(
        {
            "idempotency_key": "cb:entity-1:4853",
            "target_entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "signal_type": SignalType.CHARGEBACK_RECEIVED,
            "metadata": {
                "amount_cents": 1250,
                "currency": "USD",
                "chargeback_reason_code": "4853",
                "card_network": "VISA",
            },
        },
    )
    assert body.metadata.amount_cents == 1250
    assert body.metadata_json()["chargeback_reason_code"] == "4853"


def test_operational_signal_rejects_metadata_signal_type_mismatch() -> None:
    from orchestrator.schemas.operational_signals import OperationalSignalCreate, SignalType

    with pytest.raises(ValidationError):
        OperationalSignalCreate.model_validate(
            {
                "idempotency_key": "refund:1",
                "target_entity_id": str(UUID(int=1)),
                "signal_type": SignalType.REFUND_ISSUED,
                "metadata": {
                    "amount_cents": 100,
                    "currency": "USD",
                    "chargeback_reason_code": "4853",
                    "card_network": "VISA",
                },
            },
        )


def test_operational_signal_rejects_empty_idempotency_key() -> None:
    from orchestrator.schemas.operational_signals import OperationalSignalCreate, SignalType

    with pytest.raises(ValidationError, match="idempotency_key"):
        OperationalSignalCreate.model_validate(
            {
                "idempotency_key": "   ",
                "target_entity_id": str(UUID(int=2)),
                "signal_type": SignalType.MANUAL_OVERRIDE,
                "metadata": {
                    "override_action": "REVIEW",
                    "reason_code": "ANALYST_ESCALATION",
                    "analyst_id": "analyst-42",
                },
            },
        )


def test_operational_signal_rejects_generic_metadata_keys() -> None:
    from orchestrator.schemas.operational_signals import OperationalSignalCreate, SignalType

    with pytest.raises(ValidationError):
        OperationalSignalCreate.model_validate(
            {
                "idempotency_key": "refund:2",
                "target_entity_id": str(UUID(int=3)),
                "signal_type": SignalType.REFUND_ISSUED,
                "metadata": {
                    "amount_cents": 500,
                    "currency": "EUR",
                    "refund_reason_code": "CUSTOMER_REQUEST",
                    "refund_channel": "CUSTOMER_SERVICE",
                    "unexpected_key": "not allowed",
                },
            },
        )
