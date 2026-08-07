"""QA sampling helpers (maturity Wave 3)."""

from __future__ import annotations

from case_api.qa_sampling import disagreement_metrics, sample_case_ids


def test_sample_case_ids_deterministic():
    ids = [f"c{i}" for i in range(100)]
    a = sample_case_ids(ids, rate=0.1, seed="2026-08-05", limit=20)
    b = sample_case_ids(ids, rate=0.1, seed="2026-08-05", limit=20)
    assert a == b
    assert 1 <= len(a) <= 20


def test_disagreement_metrics():
    m = disagreement_metrics(
        [
            {"original_status": "resolved", "qa_status": "resolved"},
            {"original_status": "resolved", "qa_status": "closed"},
        ]
    )
    assert m["reviewed"] == 2
    assert m["disagree"] == 1
    assert m["agreement_rate"] == 0.5
