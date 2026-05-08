"""Tarka Python bindings."""

from tarka import _tarka
from tarka.decision import (
    TarkaDecision,
    backpressure_payload,
    evaluate,
    ingest_stats,
    rule_content_id,
    rule_expr_mermaid_flowchart,
)

BackpressureSignal = _tarka.BackpressureSignal

__all__ = [
    "BackpressureSignal",
    "TarkaDecision",
    "backpressure_payload",
    "evaluate",
    "ingest_stats",
    "rule_content_id",
    "rule_expr_mermaid_flowchart",
]
