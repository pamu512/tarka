"""Export labeled (subgraph_snapshot, y_label) rows. Skip unlabeled.

Receipts with no named edges cannot train a GNN — they may still export
when labeled (``trainable`` is false).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from decision_api.gnn_loop import CHARGEBACK_CLASSES
from decision_api.y_label_store import load_label_records


def chargeback_class_from_dispute(outcome: str) -> str:
    token = (outcome or "").strip().lower()
    if not token:
        return ""
    if token in {"fraud_confirmed", "merchant_fault", "fraud"}:
        return "FRAUD"
    if token in {"friendly_fraud", "friendly"}:
        return "FRIENDLY"
    if token in {"service", "service_issue", "product_service"}:
        return "SERVICE"
    if token in CHARGEBACK_CLASSES:
        return token
    return "UNKNOWN"


def _y_for_receipt(
    receipt: Mapping[str, Any],
    records: Mapping[str, Any],
) -> str:
    by_t = records.get("by_trace") if isinstance(records.get("by_trace"), dict) else {}
    by_e = (
        records.get("by_entity") if isinstance(records.get("by_entity"), dict) else {}
    )
    tid = str(receipt.get("trace_id") or "").strip()
    eid = str(receipt.get("entity_id") or "").strip()
    if tid and str(by_t.get(tid) or "") in {"0", "1"}:
        return str(by_t[tid])
    if eid and str(by_e.get(eid) or "") in {"0", "1"}:
        return str(by_e[eid])
    return ""


def _why_for_receipt(
    receipt: Mapping[str, Any],
    records: Mapping[str, Any],
) -> str:
    why_t = (
        records.get("why_by_trace")
        if isinstance(records.get("why_by_trace"), dict)
        else {}
    )
    why_e = (
        records.get("why_by_entity")
        if isinstance(records.get("why_by_entity"), dict)
        else {}
    )
    tid = str(receipt.get("trace_id") or "").strip()
    eid = str(receipt.get("entity_id") or "").strip()
    if tid and str(why_t.get(tid) or "").strip():
        return str(why_t[tid]).strip()
    if eid and str(why_e.get(eid) or "").strip():
        return str(why_e[eid]).strip()
    return ""


def _late_fields(
    receipt: Mapping[str, Any],
    records: Mapping[str, Any],
) -> tuple[str, str]:
    d_t = (
        records.get("dispute_outcome_by_trace")
        if isinstance(records.get("dispute_outcome_by_trace"), dict)
        else {}
    )
    c_t = (
        records.get("chargeback_class_by_trace")
        if isinstance(records.get("chargeback_class_by_trace"), dict)
        else {}
    )
    tid = str(receipt.get("trace_id") or "").strip()
    dispute = str(d_t.get(tid) or receipt.get("dispute_outcome") or "").strip()
    cls = str(c_t.get(tid) or receipt.get("chargeback_class") or "").strip().upper()
    if cls not in CHARGEBACK_CLASSES:
        cls = chargeback_class_from_dispute(dispute)
    if cls not in CHARGEBACK_CLASSES:
        cls = ""
    return dispute, cls


def _as_snapshot(receipt: Mapping[str, Any]) -> dict[str, Any]:
    raw = receipt.get("subgraph_snapshot")
    if isinstance(raw, dict) and (
        isinstance(raw.get("edges"), list) or isinstance(raw.get("vertices"), list)
    ):
        return dict(raw)
    return {
        "schema_id": receipt.get("schema_id"),
        "status": receipt.get("status"),
        "trace_id": receipt.get("trace_id"),
        "entity_id": receipt.get("entity_id"),
        "user_id": receipt.get("user_id"),
        "role": receipt.get("role"),
        "vertices": list(receipt.get("vertices") or []),
        "edges": list(receipt.get("edges") or []),
    }


def export_labeled_rows(
    tenant_id: str,
    receipts: Iterable[Mapping[str, Any]],
    *,
    records: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Join y_label + why; drop unlabeled. Edgeless rows export with trainable=false."""
    store = records if records is not None else load_label_records(tenant_id)
    rows: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        y = _y_for_receipt(receipt, store)
        if y not in {"0", "1"}:
            continue
        snap = _as_snapshot(receipt)
        edges = snap.get("edges") if isinstance(snap.get("edges"), list) else []
        dispute, cls = _late_fields(receipt, store)
        rows.append(
            {
                "trace_id": str(receipt.get("trace_id") or snap.get("trace_id") or ""),
                "entity_id": str(
                    receipt.get("entity_id") or snap.get("entity_id") or ""
                ),
                "subgraph_snapshot": snap,
                "y_label": y,
                "why": _why_for_receipt(receipt, store),
                "dispute_outcome": dispute,
                "chargeback_class": cls,
                "trainable": bool(edges),
            }
        )
    return rows


def write_export_jsonl(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), default=str))
            fh.write("\n")
    return path
