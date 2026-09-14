"""Tarka Python bindings."""

from tarka.decision import (
    TarkaDecision,
    evaluate,
    ingest_stats,
    rule_content_id,
    rule_expr_mermaid_flowchart,
)
from tarka.engine import TarkaEngine
try:
    from tarka.verifier import (
        ManifestIntegrityError,
        ManifestVerifier,
        VerificationFailureReason,
        VerificationResult,
    )
except ImportError:  # manifest verification needs PyNaCl; optional outside sealing contexts
    ManifestIntegrityError = None
    ManifestVerifier = None
    VerificationFailureReason = None
    VerificationResult = None

try:
    from tarka import _tarka

    BackpressureSignal = _tarka.BackpressureSignal
except ImportError:  # protobuf-only contexts (worker images without the native ext)
    BackpressureSignal = None

__all__ = [
    "BackpressureSignal",
    "ManifestIntegrityError",
    "ManifestVerifier",
    "TarkaDecision",
    "TarkaEngine",
    "VerificationFailureReason",
    "VerificationResult",
    "evaluate",
    "ingest_stats",
    "rule_content_id",
    "rule_expr_mermaid_flowchart",
]
