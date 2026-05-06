"""Incognia device intelligence and risk assessment adapter."""

from .client import IncogniaClient, IncogniaClientSettings, incognia_client_from_env
from .exceptions import (
    IncogniaAuthenticationError,
    IncogniaCircuitOpenError,
    IncogniaClientError,
    IncogniaIntegrationError,
    IncogniaMalformedPayloadError,
    IncogniaRateLimitError,
    IncogniaUpstreamError,
)
from .schemas import (
    IncogniaTarkaProvenance,
    IncogniaTarkaRiskSignal,
    PostFeedbackRequestBody,
    PostSignupRequestBody,
    PostTransactionRequestBody,
    SignupAssessment,
    TokenResponse,
    TransactionAssessment,
    incognia_signup_assessment_to_tarka,
    incognia_transaction_assessment_to_tarka,
    parse_assessment_json,
)

__all__ = [
    "IncogniaAuthenticationError",
    "IncogniaCircuitOpenError",
    "IncogniaClient",
    "IncogniaClientError",
    "IncogniaClientSettings",
    "IncogniaIntegrationError",
    "IncogniaMalformedPayloadError",
    "IncogniaRateLimitError",
    "IncogniaTarkaProvenance",
    "IncogniaTarkaRiskSignal",
    "IncogniaUpstreamError",
    "PostFeedbackRequestBody",
    "PostSignupRequestBody",
    "PostTransactionRequestBody",
    "SignupAssessment",
    "TokenResponse",
    "TransactionAssessment",
    "incognia_client_from_env",
    "incognia_signup_assessment_to_tarka",
    "incognia_transaction_assessment_to_tarka",
    "parse_assessment_json",
]
