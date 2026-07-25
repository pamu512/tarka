"""Tests for standardized citation schema (Q2-E02)."""

from __future__ import annotations

from investigation_agent.citation_schema import (
    CITATION_SCHEMA_VERSION,
    CitationArtifact,
    build_standard_citations,
)


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


def test_build_standard_citations_resolves_okf_concepts_exactly() -> None:
    citations, summary = build_standard_citations(
        claims=[
            {
                "text": "The high amount rule requires additional review.",
                "source": "tool",
                "concept_ids": ["rules/high-amount"],
                "evidence_ids": ["ev-high-amount"],
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
        allowed_concept_ids={"rules/high-amount"},
        allowed_evidence_ids={"ev-high-amount"},
    )

    assert CitationArtifact.OKF_CONCEPT.value == "okf_concept"
    assert citations[0]["supported"] is True
    assert citations[0]["confidence_label"] == "high"
    assert {"artifact": "okf_concept", "id": "rules/high-amount"} in citations[0]["resolves_to"]
    assert {"artifact": "evidence", "id": "ev-high-amount"} in citations[0]["resolves_to"]
    assert summary.supported_count == 1


def test_build_standard_citations_marks_unresolved_exact_refs_unsupported() -> None:
    citations, summary = build_standard_citations(
        claims=[
            {
                "text": "A claim with an unresolved OKF concept reference.",
                "source": "tool",
                "concept_ids": [" "],
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
    )

    assert citations[0]["source"] == "unknown"
    assert citations[0]["supported"] is False
    assert citations[0]["confidence_label"] == "low"
    assert citations[0]["resolves_to"] == []
    assert summary.supported_count == 0


def test_build_standard_citations_rejects_fabricated_exact_ids() -> None:
    citations, summary = build_standard_citations(
        claims=[
            {
                "text": "The fabricated rule supposedly applies.",
                "source": "tool",
                "concept_ids": ["rules/fabricated"],
                "evidence_ids": ["ev-fabricated"],
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
        allowed_concept_ids={"rules/high-amount"},
        allowed_evidence_ids={"ev-high-amount"},
    )

    assert citations[0]["source"] == "unknown"
    assert citations[0]["supported"] is False
    assert citations[0]["confidence_label"] == "low"
    assert citations[0]["resolves_to"] == []
    assert summary.supported_count == 0


def test_build_standard_citations_rejects_fabricated_resolves_to_exact_artifacts() -> None:
    citations, _ = build_standard_citations(
        claims=[
            {
                "text": "The fabricated rule supposedly applies.",
                "source": "tool",
                "resolves_to": [
                    {"artifact": "okf_concept", "id": "rules/fabricated"},
                    {"artifact": "evidence", "id": "ev-fabricated"},
                ],
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
        allowed_concept_ids={"rules/high-amount"},
        allowed_evidence_ids={"ev-high-amount"},
    )

    assert citations[0]["resolves_to"] == []
