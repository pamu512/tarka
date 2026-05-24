"""
Strict domain boundaries between risk-engine output and business-impact metrics.

``RiskDecision`` and ``BusinessImpact`` are intentionally separate roots — they do not
share a common Pydantic parent beyond ``BaseModel`` and must never inherit from one another.
"""

from __future__ import annotations

import math
import re
from typing import Any, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FINANCIAL_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)"
    r"(^|_)(amount|currency|ltv|margin|revenue|cent|cents|money|price|cost|fee|profit|loss|"
    r"usd|eur|gbp|fx|valuation|gmv|arr|mrr)(_|$|\d)"
)

_RISK_ONLY_FIELDS: Final[frozenset[str]] = frozenset(
    {"scores", "actions", "blocking_rule_id", "evaluation_trace"},
)
_BUSINESS_ONLY_FIELDS: Final[frozenset[str]] = frozenset(
    {"ltv_cents", "margin_impact_cents", "revenue_at_risk_cents"},
)


def is_unauthorized_business_metric_key(name: str) -> bool:
    """True when a JSON key carries business P&L / monetary semantics (forbidden on ``RiskDecision``)."""
    token = name.strip()
    if not token:
        return False
    if token in _BUSINESS_ONLY_FIELDS:
        return True
    return _FINANCIAL_IDENTIFIER_RE.search(token) is not None


def _reject_financial_identifier(name: str, *, context: str) -> None:
    token = name.strip()
    if not token:
        raise ValueError(f"{context} must be a non-empty identifier")
    if _FINANCIAL_IDENTIFIER_RE.search(token):
        raise ValueError(
            f"{context} {token!r} looks like a financial/business metric; "
            "use BusinessImpact for monetary fields",
        )


def _reject_risk_identifier(name: str, *, context: str) -> None:
    token = name.strip()
    if not token:
        raise ValueError(f"{context} must be a non-empty identifier")
    if token in _RISK_ONLY_FIELDS:
        raise ValueError(
            f"{context} {token!r} is a risk-decision field; use RiskDecision instead",
        )


class _RiskDomainRoot(BaseModel):
    """Marker base for fraud/risk decision payloads (not a business-metrics supertype)."""

    model_config = ConfigDict(extra="forbid")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls is _RiskDomainRoot:
            return
        for base in cls.__bases__:
            if base is _BusinessDomainRoot or (
                isinstance(base, type) and issubclass(base, _BusinessDomainRoot)
            ):
                raise TypeError(
                    f"{cls.__name__} cannot inherit from business domain types",
                )


class _BusinessDomainRoot(BaseModel):
    """Marker base for monetary business-impact payloads (not a risk-decision supertype)."""

    model_config = ConfigDict(extra="forbid")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls is _BusinessDomainRoot:
            return
        for base in cls.__bases__:
            if base is _RiskDomainRoot or (
                isinstance(base, type) and issubclass(base, _RiskDomainRoot)
            ):
                raise TypeError(
                    f"{cls.__name__} cannot inherit from risk domain types",
                )


class RiskDecision(_RiskDomainRoot):
    """
    Normalized rule-engine / policy outcome — scores and enforcement only.

    Financial metrics and currency fields are rejected at validation time.
    """

    DOMAIN: ClassVar[str] = "risk"

    scores: dict[str, float] = Field(
        default_factory=dict,
        description="Named model or policy sub-scores (non-monetary).",
    )
    actions: list[str] = Field(
        default_factory=list,
        description="Ordered policy actions (e.g. BLOCK, FLAG, SHADOW_REVIEW).",
    )
    blocking_rule_id: str | None = Field(
        default=None,
        max_length=128,
        description="Rule id that triggered a hard BLOCK, when present.",
    )
    evaluation_trace: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured per-rule evaluation trace from the rules tier.",
    )

    @field_validator("scores")
    @classmethod
    def _validate_scores(cls, value: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, raw in value.items():
            _reject_financial_identifier(str(key), context="scores key")
            if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise ValueError(f"scores[{key!r}] must be a finite number")
            out[str(key)] = float(raw)
        return out

    @field_validator("actions")
    @classmethod
    def _validate_actions(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            token = str(item).strip().upper()
            if not token:
                raise ValueError("actions entries must be non-empty strings")
            _reject_financial_identifier(token, context="actions entry")
            out.append(token)
        return out

    @field_validator("blocking_rule_id")
    @classmethod
    def _validate_blocking_rule_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = value.strip()
        if not token:
            raise ValueError("blocking_rule_id must be non-empty when provided")
        _reject_financial_identifier(token, context="blocking_rule_id")
        return token

    @field_validator("evaluation_trace")
    @classmethod
    def _validate_evaluation_trace(
        cls,
        value: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        for index, row in enumerate(value):
            if not isinstance(row, dict):
                raise ValueError(f"evaluation_trace[{index}] must be an object")
            for key in row:
                _reject_financial_identifier(str(key), context=f"evaluation_trace[{index}] key")
        return value

    @model_validator(mode="after")
    def _block_requires_rule_id(self) -> RiskDecision:
        if "BLOCK" in self.actions and self.blocking_rule_id is None:
            raise ValueError("blocking_rule_id is required when actions include BLOCK")
        return self


class BusinessImpact(_BusinessDomainRoot):
    """Monetary business metrics — strictly separated from risk decision payloads."""

    DOMAIN: ClassVar[str] = "business"

    ltv_cents: int = Field(
        ...,
        ge=0,
        description="Customer lifetime value estimate in minor currency units.",
    )
    margin_impact_cents: int = Field(
        ...,
        description="Signed margin impact in minor currency units (negative = loss).",
    )
    revenue_at_risk_cents: int = Field(
        ...,
        ge=0,
        description="Gross revenue exposed by the decision in minor currency units.",
    )

    @model_validator(mode="after")
    def _forbid_risk_field_names_in_dump(self) -> BusinessImpact:
        dumped = self.model_dump()
        overlap = _RISK_ONLY_FIELDS.intersection(dumped.keys())
        if overlap:
            raise ValueError(f"business impact cannot carry risk fields: {sorted(overlap)}")
        return self


def assert_domain_field_separation() -> None:
    """Import-time guard: field names must not overlap between domains."""
    risk_fields = set(RiskDecision.model_fields)
    business_fields = set(BusinessImpact.model_fields)
    shared = risk_fields & business_fields
    if shared:
        raise RuntimeError(f"domain boundary violation: shared fields {sorted(shared)}")


assert_domain_field_separation()


def risk_decision_from_rule_engine_payload(payload: dict[str, Any]) -> RiskDecision:
    """
    Lift a rule-engine JSON body into ``RiskDecision``, rejecting business metrics keys.
    """
    if not isinstance(payload, dict):
        raise TypeError("payload must be a mapping")
    for key in payload:
        if key in _BUSINESS_ONLY_FIELDS:
            raise ValueError(
                f"rule-engine payload key {key!r} belongs on BusinessImpact, not RiskDecision",
            )
        _reject_financial_identifier(str(key), context="rule-engine payload key")
    return RiskDecision.model_validate(
        {
            "scores": payload.get("scores", {}),
            "actions": payload.get("actions", []),
            "blocking_rule_id": payload.get("blocking_rule_id"),
            "evaluation_trace": payload.get("evaluation_trace", []),
        },
    )
