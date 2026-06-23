"""Tests for standardized citation schema (Q2-E02)."""

from __future__ import annotations

from investigation_agent.citation_schema import CITATION_SCHEMA_VERSION, build_standard_citations


def test_build_standard_citations_shape() -> None:
    claims = [
        {"text": "Trace abc was reviewed.", "source": "tool"},
        {"text": "Unknown inference.", "source": "unknown"},
    ]
    support = [
        {"claim_index": 0, "supported": True, "method": "token_overlap"},
        {"claim_index": 1, "supported": False, "method": "token_overlap"},
    ]
    citations, summary = build_standard_citations(
        claims=claims,
        deterministic_support=support,
        trace_id="trace-1",
        case_id="case-1",
    )
    assert len(citations) == 2
    assert citations[0]["confidence_label"] == "high"
    assert citations[1]["confidence_label"] == "low"
    assert summary.schema_version == CITATION_SCHEMA_VERSION
    assert summary.supported_count == 1
    assert summary.validity_rate == 0.5
