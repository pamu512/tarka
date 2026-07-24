from __future__ import annotations

import json
from pathlib import Path

from investigation_agent.citation_schema import build_standard_citations
from investigation_agent.main import (
    _enforce_claim_exact_ids,
    _parse_tarka_claims_reply,
)


def test_independent_adversarial_citation_quality_gate() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "citation_quality_cases_v1.json").read_text(
            encoding="utf-8"
        )
    )
    tool_calls = fixture["tool_calls"]
    allowed_concepts = {
        str(hit["concept_id"]) for call in tool_calls for hit in call["result"]["hits"]
    }
    allowed_evidence = {
        str(evidence_id)
        for call in tool_calls
        for hit in call["result"]["hits"]
        for evidence_id in hit["evidence_ids"]
    }

    accepted_exact_refs = 0
    correct_exact_refs = 0
    unsupported_total = 0
    unsupported_abstained = 0
    categories: set[str] = set()
    for case in fixture["cases"]:
        name = str(case["name"])
        prefix, separator, suffix = name.rpartition("_")
        categories.add(prefix if separator and suffix.isdigit() else name)
        raw_reply = "Fixture answer.\nTARKA_CLAIMS_JSON=" + json.dumps(
            {"claims": [case["claim"]]}, separators=(",", ":")
        )
        _prose, parsed, warning = _parse_tarka_claims_reply(raw_reply)
        assert warning is None, case["name"]
        grounded, _adjustments = _enforce_claim_exact_ids(parsed, tool_calls)
        citations, _summary = build_standard_citations(
            claims=grounded,
            deterministic_support=[
                {
                    "claim_index": 0,
                    "supported": grounded[0].get("source") == "tool"
                    and grounded[0].get("supported") is not False,
                }
            ],
            allowed_concept_ids=allowed_concepts,
            allowed_evidence_ids=allowed_evidence,
        )
        card = citations[0]
        resolved_exact = {
            (str(ref["artifact"]), str(ref["id"]))
            for ref in card["resolves_to"]
            if ref["artifact"] in {"okf_concept", "evidence"}
        }
        accepted = resolved_exact if card["supported"] is True else set()
        expected = {(str(ref[0]), str(ref[1])) for ref in case.get("expected_refs", [])}
        accepted_exact_refs += len(accepted)
        correct_exact_refs += len(accepted & expected)

        if case["expected_supported"]:
            assert accepted == expected, case["name"]
        else:
            unsupported_total += 1
            unsupported_abstained += int(card["source"] == "unknown" and card["supported"] is False)

    assert {
        "correct_exact_ids",
        "fabricated_ids",
        "nonexistent_ids",
        "unrelated_valid_ids",
        "omitted_ids",
        "omitted_index",
    } <= categories
    assert unsupported_total >= 20
    assert accepted_exact_refs > 0
    citation_resolution_precision = correct_exact_refs / accepted_exact_refs
    unsupported_abstention = unsupported_abstained / unsupported_total
    assert citation_resolution_precision >= 0.995
    assert unsupported_abstention >= 0.98
