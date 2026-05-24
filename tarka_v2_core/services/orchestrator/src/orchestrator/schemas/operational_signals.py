"""Operational signal schemas — extends :mod:`operational` with production extensions."""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestrator.config import get_settings
from orchestrator.schemas.operational import (
    CardNetwork,
    ChargebackReceivedMetadata,
    ManualOverrideAction,
    ManualOverrideMetadata,
    OperationalSignalAcceptedResponse,
    RefundChannel,
    RefundIssuedMetadata,
    _IDEMPOTENCY_KEY_RE,
    _REASON_CODE_RE,
)

__all__ = [
    "CardNetwork",
    "ChargebackReceivedMetadata",
    "ChargebackReversedMetadata",
    "ManualOverrideAction",
    "ManualOverrideMetadata",
    "OperationalSignalAcceptedResponse",
    "OperationalSignalCreate",
    "RefundChannel",
    "RefundIssuedMetadata",
    "SignalType",
    "metadata_model_for_signal",
]


class SignalType(str, Enum):
    CHARGEBACK_RECEIVED = "CHARGEBACK_RECEIVED"
    CHARGEBACK_REVERSED = "CHARGEBACK_REVERSED"
    REFUND_ISSUED = "REFUND_ISSUED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class ChargebackReversedMetadata(BaseModel):
    """Structured payload for ``CHARGEBACK_REVERSED`` signals."""

    model_config = ConfigDict(extra="forbid")

    amount_cents: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    chargeback_reason_code: str = Field(..., min_length=1, max_length=32)
    reversal_reason_code: str = Field(..., min_length=1, max_length=32)
    original_signal_idempotency_key: str = Field(..., min_length=1, max_length=255)

    @field_validator("chargeback_reason_code", "reversal_reason_code")
    @classmethod
    def _validate_reason_codes(cls, v: str) -> str:
        token = v.strip().upper()
        max_len = get_settings().operational_signal_reason_code_max_length
        if len(token) > max_len:
            raise ValueError(f"reason code must be at most {max_len} characters")
        if not _REASON_CODE_RE.fullmatch(token):
            raise ValueError("reason code must match [A-Z0-9][A-Z0-9._-]{0,31}")
        return token

    @field_validator("original_signal_idempotency_key")
    @classmethod
    def _validate_original_key(cls, v: str) -> str:
        token = v.strip()
        max_len = get_settings().operational_signal_idempotency_key_max_length
        if not token:
            raise ValueError("original_signal_idempotency_key must be non-empty")
        if len(token) > max_len:
            raise ValueError(f"original_signal_idempotency_key must be at most {max_len} characters")
        if not _IDEMPOTENCY_KEY_RE.fullmatch(token):
            raise ValueError("original_signal_idempotency_key has invalid characters or shape")
        return token


_METADATA_BY_SIGNAL: dict[SignalType, type[BaseModel]] = {
    SignalType.CHARGEBACK_RECEIVED: ChargebackReceivedMetadata,
    SignalType.CHARGEBACK_REVERSED: ChargebackReversedMetadata,
    SignalType.REFUND_ISSUED: RefundIssuedMetadata,
    SignalType.MANUAL_OVERRIDE: ManualOverrideMetadata,
}


def metadata_model_for_signal(signal_type: SignalType) -> type[BaseModel]:
    return _METADATA_BY_SIGNAL[signal_type]


class OperationalSignalCreate(BaseModel):
    """
    Ingress contract for ``operational_signals`` rows.

    Accepts ``target_entity_id`` (production wire name) or ``entity_id`` (core schema name).
    """

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=1, max_length=255)
    target_entity_id: UUID
    signal_type: SignalType
    metadata: (
        ChargebackReceivedMetadata
        | ChargebackReversedMetadata
        | RefundIssuedMetadata
        | ManualOverrideMetadata
    )

    @field_validator("idempotency_key")
    @classmethod
    def _validate_idempotency_key(cls, v: str) -> str:
        token = v.strip()
        max_len = get_settings().operational_signal_idempotency_key_max_length
        if not token:
            raise ValueError("idempotency_key must be a non-empty string")
        if len(token) > max_len:
            raise ValueError(f"idempotency_key must be at most {max_len} characters")
        if not _IDEMPOTENCY_KEY_RE.fullmatch(token):
            raise ValueError("idempotency_key has invalid characters or shape")
        return token

    @model_validator(mode="before")
    @classmethod
    def _normalize_entity_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and "target_entity_id" not in data and "entity_id" in data:
            out = dict(data)
            out["target_entity_id"] = out["entity_id"]
            return out
        return data

    @model_validator(mode="before")
    @classmethod
    def _coerce_metadata_for_signal_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        signal_raw = data.get("signal_type")
        metadata_raw = data.get("metadata")
        if signal_raw is None or metadata_raw is None:
            return data
        if not isinstance(metadata_raw, dict):
            return data
        try:
            signal_type = (
                signal_raw if isinstance(signal_raw, SignalType) else SignalType(str(signal_raw).strip())
            )
        except ValueError:
            return data
        model_cls = _METADATA_BY_SIGNAL[signal_type]
        out = dict(data)
        out["metadata"] = model_cls.model_validate(metadata_raw)
        return out

    @model_validator(mode="after")
    def _metadata_matches_signal_type(self) -> OperationalSignalCreate:
        expected = _METADATA_BY_SIGNAL[self.signal_type]
        if not isinstance(self.metadata, expected):
            raise ValueError(
                f"metadata shape does not match signal_type={self.signal_type.value!r} "
                f"(expected {expected.__name__})",
            )
        return self

    @property
    def entity_id(self) -> UUID:
        return self.target_entity_id

    def metadata_json(self) -> dict[str, Any]:
        dumped = self.metadata.model_dump(mode="json")
        assert isinstance(dumped, dict)
        return dumped
