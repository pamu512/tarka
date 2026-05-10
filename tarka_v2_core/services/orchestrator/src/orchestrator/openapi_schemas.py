"""OpenAPI response and error models for ReDoc / OpenAPI generation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValidationErrorItem(BaseModel):
    """One field-level validation failure."""

    loc: list[str | int] = Field(
        ...,
        description="Location of the invalid value (e.g. `body`, field name, nested keys).",
        examples=[["body", "amount"]],
    )
    msg: str = Field(..., description="Explanation suitable for API consumers.")
    type: str = Field(..., description="Machine-readable error type identifier.")


class HTTPValidationError422(BaseModel):
    """Returned when the JSON body does not satisfy the published request schema."""

    detail: list[ValidationErrorItem]


class IngestResponse(BaseModel):
    """Successful `/v1/ingest` response: policy outcome plus optional secondary analysis."""

    model_config = ConfigDict(extra="allow")

    rule_engine: dict[str, Any] = Field(
        ...,
        description=(
            "Opaque policy evaluation payload returned to callers "
            "(for example actions and identifiers produced by the rules tier)."
        ),
    )
    transaction_id: str = Field(
        ...,
        description="UUID string matching the submitted transaction `entity_id`.",
    )
    shadow_agent: dict[str, Any] | None = Field(
        None,
        description=(
            "Structured fraud-analysis output when a secondary review step completed successfully."
        ),
    )
    orchestrator_fallback_decision: str | None = Field(
        None,
        description="When secondary review was requested but did not return a body, may be `FLAG`.",
    )
    orchestrator_fallback_reason: str | None = Field(
        None,
        description="Machine-readable reason for fallback (timeout, transport failure, etc.).",
    )
    orchestrator_shadow_deadline_seconds: float | None = Field(
        None,
        description="Read deadline used for secondary review when a timeout fallback occurred.",
    )


class ServiceProbe(BaseModel):
    """Single component row in the aggregate health matrix."""

    component: str
    status: str
    latency_ms: float | None = None
    detail: str


class HealthFullResponse(BaseModel):
    """Aggregate readiness snapshot across orchestrator and configured dependencies."""

    generated_at: str = Field(
        ...,
        description="UTC timestamp (ISO 8601) when this snapshot was produced.",
    )
    services: list[ServiceProbe] = Field(
        ...,
        description="Per-component status, round-trip latency where applicable, and short detail text.",
    )


class DemoResultRow(BaseModel):
    """One simulated transaction row for UI demonstrations."""

    pattern_index: int
    total: int
    transaction_id: str
    amount: float
    currency: str
    channel: str
    shadow_verdict: str
    integrity_confidence: float
    simulated_at: str


class DemoSimulateResponse(BaseModel):
    """Fixed-size batch of simulated results for attack-pattern visualization."""

    total: int = Field(..., description="Length of the `results` array.")
    results: list[DemoResultRow]


class BadGateway502(BaseModel):
    """Upstream dependency returned an HTTP error or violated the expected contract."""

    detail: dict[str, Any] = Field(
        ...,
        description=(
            "Structured diagnostic payload including error class, upstream HTTP status, "
            "and a truncated response preview."
        ),
    )


class ServiceUnavailable503(BaseModel):
    """Gateway could not reach an upstream dependency or complete configuration checks."""

    detail: str | dict[str, Any] = Field(
        ...,
        description="Plain string or structured object describing the failure.",
    )
