"""Pydantic v2 models for Incognia REST API and Tarka normalization.

Field names use **camelCase** on request/response bodies to match the Java SDK's
Jackson defaults (see ``incognia-api-java``).

References:
- https://github.com/inloco/incognia-api-java
- https://dash.incognia.com/api-reference
"""

from __future__ import annotations

import math
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .exceptions import IncogniaMalformedPayloadError

IncogniaRiskAssessment = Literal["low_risk", "high_risk", "unknown_risk"]


# --- OAuth token ---


class TokenResponse(BaseModel):
    """``POST api/v2/token`` JSON body (camelCase per Java ``TokenResponse``)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    access_token: str = Field(validation_alias=AliasChoices("accessToken", "access_token"))
    expires_in: int = Field(validation_alias=AliasChoices("expiresIn", "expires_in"), ge=0)
    token_type: str = Field(validation_alias=AliasChoices("tokenType", "token_type"))


# --- Shared value objects (subset used by POST bodies) ---


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lat: float
    lng: float


class StructuredAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    locale: str | None = None
    countryName: str | None = None
    countryCode: str | None = None
    state: str | None = None
    county: str | None = None
    city: str | None = None
    borough: str | None = None
    neighborhood: str | None = None
    street: str | None = None
    number: str | None = None
    complements: str | None = None
    postalCode: str | None = None


class PersonID(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    value: str | None = None


class Location(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latitude: str | None = None
    longitude: str | None = None
    collectedAt: str | None = None


class TransactionAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    addressLine: str | None = None
    structuredAddress: StructuredAddress | None = None
    addressCoordinates: Coordinates | None = None


class FinancialAccount(BaseModel):
    """Optional nested object on feedback; extra fields allowed for forward compatibility."""

    model_config = ConfigDict(extra="allow")

    accountNumber: str | None = None
    branchCode: str | None = None
    holderType: str | None = None
    accountCheckDigit: str | None = None
    accountPurpose: str | None = None
    accountType: str | None = None
    country: str | None = None
    ispbCode: str | None = None


# --- Request bodies (Java ``PostSignupRequestBody`` / ``PostTransactionRequestBody``) ---


class PostSignupRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    installationId: str | None = None
    sessionToken: str | None = None
    requestToken: str | None = None
    addressLine: str | None = None
    appVersion: str | None = None
    deviceOs: str | None = None
    structuredAddress: StructuredAddress | None = None
    addressCoordinates: Coordinates | None = None
    externalId: str | None = None
    policyId: str | None = None
    accountId: str | None = None
    additionalLocations: list[Any] | None = None
    personId: PersonID | None = None
    customProperties: dict[str, Any] | None = None
    relatedWebRequestToken: str | None = None
    tenantId: str | None = None


class PostTransactionRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    installationId: str | None = None
    requestToken: str | None = None
    appVersion: str | None = None
    deviceOs: str | None = None
    accountId: str | None = None
    sessionToken: str | None = None
    policyId: str | None = None
    type: str | None = None
    storeId: str | None = None
    externalId: str | None = None
    relatedAccountId: str | None = None
    location: Location | dict[str, Any] | None = None
    coupon: dict[str, Any] | None = None
    personId: PersonID | None = None
    debtorAccount: dict[str, Any] | None = None
    creditorAccount: dict[str, Any] | None = None
    addresses: list[TransactionAddress | dict[str, Any]] | None = None
    paymentValue: dict[str, Any] | None = None
    paymentMethods: list[Any] | None = None
    customProperties: dict[str, Any] | None = None
    relatedWebRequestToken: str | None = None
    tenantId: str | None = None


FeedbackEventLiteral = Literal[
    "signup_accepted",
    "signup_declined",
    "payment_accepted",
    "payment_accepted_by_third_party",
    "payment_accepted_by_control_group",
    "payment_declined",
    "payment_declined_by_risk_analysis",
    "payment_declined_by_manual_review",
    "payment_declined_by_business",
    "payment_declined_by_acquirer",
    "login_accepted",
    "login_declined",
    "verified",
    "identity_fraud",
    "account_takeover",
    "chargeback_notification",
    "chargeback",
    "mpos_fraud",
    "challenge_passed",
    "challenge_failed",
    "password_changed_successfully",
    "password_change_failed",
    "promotion_abuse",
    "custom_other_fraud",
    "custom_discipline_block",
    "custom_pos_atm_fraud",
    "custom_collusion_fraud",
    "custom_cargo_fraud",
    "custom_debt_churn_20d",
    "custom_cancellation",
    "account_allowed",
    "device_allowed",
    "login_accepted_by_device_verification",
    "login_accepted_by_facial_biometrics",
    "login_accepted_by_manual_review",
    "login_declined_by_facial_biometrics",
    "login_declined_by_manual_review",
    "reset",
]


class PostFeedbackRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event: FeedbackEventLiteral
    timestamp: int
    accountId: str | None = None
    externalId: str | None = None
    installationId: str | None = None
    sessionToken: str | None = None
    requestToken: str | None = None
    paymentId: str | None = None
    loginId: str | None = None
    signupId: str | None = None
    expiresAt: str | None = None
    personId: PersonID | None = None
    financialAccount: FinancialAccount | dict[str, Any] | None = None


# --- Assessment responses ---


class Reason(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str | None = None
    source: str | None = None


class SignupAssessment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UUID
    requestId: UUID | None = None
    riskAssessment: IncogniaRiskAssessment | None = None
    reasons: list[Any] = Field(default_factory=list)
    actions: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
    signals: dict[str, Any] | None = None
    deviceId: str | None = None
    installationId: str | None = None


class TransactionAssessment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UUID
    riskAssessment: IncogniaRiskAssessment | None = None
    reasons: list[Any] = Field(default_factory=list)
    actions: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
    signals: dict[str, Any] | None = None
    deviceId: str | None = None
    installationId: str | None = None


# --- Tarka unified outbound (parallel shape to Fingerprint ``TarkaRiskSignal``) ---


class IncogniaTarkaProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: Literal["incognia"] = "incognia"
    assessment_id: UUID
    signup_request_id: UUID | None = None
    installation_id: str | None = None
    device_id: str | None = None
    api_base_url: str


class IncogniaTarkaRiskSignal(BaseModel):
    """Normalized risk signal for downstream engines (Incognia branch)."""

    model_config = ConfigDict(extra="forbid")

    score_0_100: float = Field(..., ge=0.0, le=100.0)
    reason_codes: list[str]
    vendor: Literal["incognia"] = "incognia"
    provenance: IncogniaTarkaProvenance
    features: dict[str, Any] = Field(default_factory=dict)


def _reason_entries(reasons: list[Any]) -> list[str]:
    codes: list[str] = []
    for item in reasons:
        if isinstance(item, Reason):
            if item.code:
                codes.append(f"incognia:{item.code}" + (f":{item.source}" if item.source else ""))
            continue
        if isinstance(item, dict):
            code = item.get("code")
            if isinstance(code, str) and code:
                src = item.get("source")
                codes.append(
                    f"incognia:{code}" + (f":{src}" if isinstance(src, str) and src else "")
                )
    return codes


def _base_score(level: IncogniaRiskAssessment | None) -> float:
    if level == "high_risk":
        return 85.0
    if level == "low_risk":
        return 15.0
    return 50.0


def _bump_for_reasons(score: float, reasons: list[str]) -> float:
    if not reasons:
        return score
    return min(100.0, score + min(12.0, 2.0 * len(reasons)))


def incognia_signup_assessment_to_tarka(
    assessment: SignupAssessment,
    *,
    api_base_url: str,
) -> IncogniaTarkaRiskSignal:
    """Map ``SignupAssessment`` to ``IncogniaTarkaRiskSignal``."""

    codes = _reason_entries(assessment.reasons)
    base = _base_score(assessment.riskAssessment)
    score = float(max(0.0, min(100.0, math.ceil(_bump_for_reasons(base, codes)))))

    features: dict[str, Any] = {
        "risk_assessment": assessment.riskAssessment,
        "actions": assessment.actions,
        "evidence": assessment.evidence,
        "signals": assessment.signals,
    }

    return IncogniaTarkaRiskSignal(
        score_0_100=score,
        reason_codes=(codes if codes else ["incognia:assessment_ok"]),
        provenance=IncogniaTarkaProvenance(
            assessment_id=assessment.id,
            signup_request_id=assessment.requestId,
            installation_id=assessment.installationId,
            device_id=assessment.deviceId,
            api_base_url=api_base_url.rstrip("/"),
        ),
        features=features,
    )


def incognia_transaction_assessment_to_tarka(
    assessment: TransactionAssessment,
    *,
    api_base_url: str,
) -> IncogniaTarkaRiskSignal:
    """Map ``TransactionAssessment`` to ``IncogniaTarkaRiskSignal``."""

    codes = _reason_entries(assessment.reasons)
    base = _base_score(assessment.riskAssessment)
    score = float(max(0.0, min(100.0, math.ceil(_bump_for_reasons(base, codes)))))

    features: dict[str, Any] = {
        "risk_assessment": assessment.riskAssessment,
        "actions": assessment.actions,
        "evidence": assessment.evidence,
        "signals": assessment.signals,
    }

    return IncogniaTarkaRiskSignal(
        score_0_100=score,
        reason_codes=(codes if codes else ["incognia:assessment_ok"]),
        provenance=IncogniaTarkaProvenance(
            assessment_id=assessment.id,
            signup_request_id=None,
            installation_id=assessment.installationId,
            device_id=assessment.deviceId,
            api_base_url=api_base_url.rstrip("/"),
        ),
        features=features,
    )


def parse_assessment_json(
    data: dict[str, Any], *, kind: Literal["signup", "transaction"]
) -> SignupAssessment | TransactionAssessment:
    """Parse a successful JSON object into the appropriate assessment model."""

    try:
        if kind == "signup":
            return SignupAssessment.model_validate(data)
        return TransactionAssessment.model_validate(data)
    except Exception as e:
        raise IncogniaMalformedPayloadError(
            f"Incognia assessment JSON failed validation: {e}"
        ) from e
