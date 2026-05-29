"""Strict Pydantic v2 schemas for operational signal ingress (core contract)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_IDEMPOTENCY_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/+-]{0,254}$")
_REASON_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_OPERATOR_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/+-]{0,127}$")


class SignalType(str, Enum):
    CHARGEBACK_RECEIVED = "CHARGEBACK_RECEIVED"
    REFUND_ISSUED = "REFUND_ISSUED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class CardNetwork(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    AMEX = "AMEX"
    DISCOVER = "DISCOVER"
    OTHER = "OTHER"


class RefundChannel(str, Enum):
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
    MERCHANT_INITIATED = "MERCHANT_INITIATED"
    AUTOMATED = "AUTOMATED"
    OTHER = "OTHER"


class ManualOverrideAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"
    FLAG = "FLAG"


class ChargebackReceivedMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    chargeback_reason_code: str = Field(..., min_length=1, max_length=32)
    card_network: CardNetwork

    @field_validator("chargeback_reason_code")
    @classmethod
    def _validate_reason_code(cls, v: str) -> str:
        token = v.strip().upper()
        if not _REASON_CODE_RE.fullmatch(token):
            raise ValueError("chargeback_reason_code must match [A-Z0-9][A-Z0-9._-]{0,31}")
        return token


class RefundIssuedMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    refund_reason_code: str = Field(..., min_length=1, max_length=32)
    refund_channel: RefundChannel

    @field_validator("refund_reason_code")
    @classmethod
    def _validate_refund_reason(cls, v: str) -> str:
        token = v.strip().upper()
        if not _REASON_CODE_RE.fullmatch(token):
            raise ValueError("refund_reason_code must match [A-Z0-9][A-Z0-9._-]{0,31}")
        return token


class ManualOverrideMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_action: ManualOverrideAction
    reason_code: str = Field(..., min_length=1, max_length=64)
    analyst_id: str = Field(..., min_length=1, max_length=128)
    prior_decision: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=4096)

    @field_validator("reason_code", "prior_decision")
    @classmethod
    def _normalize_reason(cls, v: str | None) -> str | None:
        if v is None:
            return None
        token = v.strip().upper()
        if not token:
            raise ValueError("reason fields must be non-empty when provided")
        if not _REASON_CODE_RE.fullmatch(token):
            raise ValueError("reason_code must match [A-Z0-9][A-Z0-9._-]{0,31}")
        return token

    @field_validator("analyst_id")
    @classmethod
    def _validate_analyst_id(cls, v: str) -> str:
        token = v.strip()
        if not token:
            raise ValueError("analyst_id must be non-empty")
        if not _OPERATOR_ID_RE.fullmatch(token):
            raise ValueError("analyst_id has invalid characters or shape")
        return token


_METADATA_BY_SIGNAL: dict[SignalType, type[BaseModel]] = {
    SignalType.CHARGEBACK_RECEIVED: ChargebackReceivedMetadata,
    SignalType.REFUND_ISSUED: RefundIssuedMetadata,
    SignalType.MANUAL_OVERRIDE: ManualOverrideMetadata,
}


def metadata_model_for_signal(signal_type: SignalType) -> type[BaseModel]:
    return _METADATA_BY_SIGNAL[signal_type]


class OperationalSignalCreate(BaseModel):
    """
    Ingress contract for ``operational_signals`` rows.

    ``metadata`` is validated against a strict child schema selected by ``signal_type``.
    """

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=1, max_length=255)
    entity_id: UUID = Field(
        ..., description="Transaction or case entity UUID the signal applies to."
    )
    signal_type: SignalType
    metadata: ChargebackReceivedMetadata | RefundIssuedMetadata | ManualOverrideMetadata

    @field_validator("idempotency_key")
    @classmethod
    def _validate_idempotency_key(cls, v: str) -> str:
        token = v.strip()
        if not token:
            raise ValueError("idempotency_key must be a non-empty string")
        if len(token) > 255:
            raise ValueError("idempotency_key must be at most 255 characters")
        if not _IDEMPOTENCY_KEY_RE.fullmatch(token):
            raise ValueError("idempotency_key has invalid characters or shape")
        return token

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
                signal_raw
                if isinstance(signal_raw, SignalType)
                else SignalType(str(signal_raw).strip())
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

    def metadata_json(self) -> dict[str, Any]:
        dumped = self.metadata.model_dump(mode="json")
        assert isinstance(dumped, dict)
        return dumped


class OperationalSignalAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(..., description="Internal ``operational_signals.id`` UUID.")
    status: Literal["ACCEPTED"] = "ACCEPTED"
