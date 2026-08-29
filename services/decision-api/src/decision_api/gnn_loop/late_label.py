"""Bind a delayed chargeback/dispute outcome to the evaluate snapshot.

Attaches ``dispute.outcome`` + join key onto the existing y_label store.
Does not reconstruct features or invent neighbors. Missing snapshot still
records the label with ``trainable: false``.
"""

from __future__ import annotations

from typing import Any

from decision_api.gnn_loop import CHARGEBACK_CLASSES
from decision_api.gnn_loop.receipts import find_receipt
from decision_api.y_label_store import merge_y_labels

SCHEMA_ID = "tarka.late_label/v1"


class LateLabelError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def normalize_outcome(outcome: str) -> str:
    token = (outcome or "").strip().upper()
    if token not in CHARGEBACK_CLASSES:
        raise LateLabelError(
            "invalid_outcome",
            "dispute.outcome must be one of FRAUD, FRIENDLY, SERVICE, UNKNOWN",
        )
    return token


def y_label_for_outcome(outcome: str) -> str:
    """FRAUD is 1. FRIENDLY / SERVICE / UNKNOWN are still labels (0)."""
    token = normalize_outcome(outcome)
    return "1" if token == "FRAUD" else "0"


def _edges_of(receipt: dict[str, Any] | None) -> list[Any]:
    if not isinstance(receipt, dict):
        return []
    raw = receipt.get("subgraph_snapshot")
    blob = raw if isinstance(raw, dict) else receipt
    edges = blob.get("edges")
    return edges if isinstance(edges, list) else []


def bind_late_label(
    tenant_id: str,
    *,
    outcome: str,
    trace_id: str = "",
    evaluation_token: str = "",
) -> dict[str, Any]:
    """Join late outcome onto the original receipt. Never rebuilds a graph."""
    tenant = (tenant_id or "").strip()
    if not tenant:
        raise LateLabelError("missing_tenant", "tenant_id is required")
    join = (trace_id or evaluation_token or "").strip()
    if not join:
        raise LateLabelError(
            "missing_join_key", "trace_id or evaluation_token is required"
        )
    token = normalize_outcome(outcome)
    y = y_label_for_outcome(token)
    receipt = find_receipt(tenant, join)
    merge_y_labels(
        tenant,
        by_trace={join: y},
        dispute_outcome_by_trace={join: token},
        chargeback_class_by_trace={join: token},
    )
    return {
        "ok": True,
        "schema_id": SCHEMA_ID,
        "tenant_id": tenant,
        "trace_id": join,
        "dispute_outcome": token,
        "chargeback_class": token,
        "y_label": y,
        "snapshot_bound": receipt is not None,
        "trainable": receipt is not None and bool(_edges_of(receipt)),
    }
