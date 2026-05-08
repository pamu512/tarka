"""Tarka Python bindings."""

from tarka import _tarka
from tarka.decision import (
    TarkaDecision,
    evaluate,
    ingest_stats,
    rule_content_id,
    rule_expr_mermaid_flowchart,
)
from tarka.engine import TarkaEngine
from tarka.verifier import (
    ManifestIntegrityError,
    ManifestVerifier,
    VerificationFailureReason,
    VerificationResult,
)

BackpressureSignal = _tarka.BackpressureSignal

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
