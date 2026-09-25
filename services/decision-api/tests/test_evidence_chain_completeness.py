"""Evidence-chain completeness metric (P1 proof-grade).

Per-tenant ratio of decisions whose evidence chain is complete
(receipt exists AND label state known) over a window. null = unknown
per bake-off rules — never 0.0 theater.
"""

from __future__ import annotations

from decision_api.loop_metrics import compute_evidence_chain_completeness


def test_complete_chain_scores_one():
    receipts = [
        {"tenant_id": "t1", "trace_id": "a", "label_state": "bound"},
        {"tenant_id": "t1", "trace_id": "b", "label_state": "bound"},
    ]
    out = compute_evidence_chain_completeness(receipts, tenant_id="t1")
    assert out == {"complete": 2, "total": 2, "ratio": 1.0}


def test_missing_label_reduces_ratio():
    receipts = [
        {"tenant_id": "t1", "trace_id": "a", "label_state": "bound"},
        {"tenant_id": "t1", "trace_id": "b", "label_state": "pending"},
    ]
    out = compute_evidence_chain_completeness(receipts, tenant_id="t1")
    assert out == {"complete": 1, "total": 2, "ratio": 0.5}


def test_no_receipts_is_unknown_not_zero():
    out = compute_evidence_chain_completeness([], tenant_id="t1")
    assert out == {"complete": None, "total": 0, "ratio": None}


def test_missing_label_state_counts_incomplete():
    receipts = [
        {"tenant_id": "t1", "trace_id": "a"},
        {"tenant_id": "t1", "trace_id": "b", "label_state": "bound"},
    ]
    out = compute_evidence_chain_completeness(receipts, tenant_id="t1")
    assert out["ratio"] == 0.5


def test_tenant_scoping_filters_rows():
    receipts = [
        {"tenant_id": "t1", "trace_id": "a", "label_state": "bound"},
        {"tenant_id": "t2", "trace_id": "b", "label_state": "pending"},
    ]
    out = compute_evidence_chain_completeness(receipts, tenant_id="t1")
    assert out == {"complete": 1, "total": 1, "ratio": 1.0}


def test_blank_tenant_is_unknown():
    out = compute_evidence_chain_completeness(
        [{"trace_id": "a", "label_state": "bound"}], tenant_id=""
    )
    assert out["ratio"] is None
