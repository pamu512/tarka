"""Bind a delayed label to the evaluate snapshot.

Chargeback ``dispute.outcome`` stays. Frontline FP, override-then-fraud, and
follow-on evaluate join the same y_label store. Does not reconstruct features
or invent a Care/CRM inbox. Missing snapshot still records the label with
``trainable: false``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decision_api.gnn_loop import CHARGEBACK_CLASSES
from decision_api.gnn_loop.receipts import (
    find_override_receipt,
    find_prior_receipt_for_entity,
    find_receipt,
)
from decision_api.y_label_store import merge_y_labels

SCHEMA_ID = "tarka.late_label/v1"
LABEL_KINDS = frozenset(
    {"fp", "fraud", "other", "promo_abuse", "collusion", "chargeback"}
)
LABEL_SOURCES = frozenset({"care", "finance", "crm", "evaluate"})
RESTRICTIVE_DECISIONS = frozenset(
    {"deny", "block", "review", "step_up", "step-up", "stepup", "challenge"}
)


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


def normalize_label_kind(kind: str) -> str:
    token = (kind or "").strip().lower()
    if token not in LABEL_KINDS:
        raise LateLabelError(
            "invalid_label_kind",
            "label_kind must be one of fp, fraud, other, promo_abuse, collusion, chargeback",
        )
    return token


def normalize_source(source: str) -> str:
    token = (source or "").strip().lower()
    if token not in LABEL_SOURCES:
        raise LateLabelError(
            "invalid_source",
            "source must be one of care, finance, crm, evaluate",
        )
    return token


def y_label_for_outcome(outcome: str) -> str:
    """FRAUD is 1. FRIENDLY / SERVICE / UNKNOWN are still labels (0)."""
    token = normalize_outcome(outcome)
    return "1" if token == "FRAUD" else "0"


def y_label_for_kind(kind: str) -> str:
    return "1" if normalize_label_kind(kind) == "fraud" else "0"


def _edges_of(receipt: dict[str, Any] | None) -> list[Any]:
    if not isinstance(receipt, dict):
        return []
    raw = receipt.get("subgraph_snapshot")
    blob = raw if isinstance(raw, dict) else receipt
    edges = blob.get("edges")
    return edges if isinstance(edges, list) else []


def _hits_of(receipt: dict[str, Any] | None) -> list[str]:
    if not isinstance(receipt, dict):
        return []
    raw = receipt.get("rule_hits")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x).strip()]


def parse_fp_cost(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return {"ordinal": float(raw), "counted": True}
    if isinstance(raw, dict):
        out: dict[str, Any] = {"counted": True}
        if raw.get("amount") is not None and raw.get("amount") != "":
            out["amount"] = float(raw["amount"])
        currency = str(raw.get("currency") or "").strip()
        if currency:
            out["currency"] = currency[:8]
        if raw.get("ordinal") is not None and raw.get("ordinal") != "":
            out["ordinal"] = float(raw["ordinal"])
        return out
    return {"counted": True}


def _mint_soften_draft(
    tenant_id: str,
    receipt: dict[str, Any] | None,
    store_key: str,
    fp_cost: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Write a human/seed Observe pack. Never Active."""
    try:
        from decision_api.config import settings
        from decision_api.l2_draft import L2DraftError, build_l2_draft, find_open_draft
    except ImportError:
        return None
    rules_dir = Path(settings.rules_path)
    rules_dir.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    for path in rules_dir.glob("*.json"):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(blob, dict):
            blob["_file"] = path.name
            existing.append(blob)
    hit = find_open_draft(existing, leftover_id="", hil_event_id=store_key)
    if hit:
        return {"file": hit.get("_file"), "pack": hit, "duplicate": True}
    rec = receipt if isinstance(receipt, dict) else {}
    try:
        pack = build_l2_draft(
            receipt={
                "tenant_id": rec.get("tenant_id") or tenant_id,
                "entity_id": rec.get("entity_id") or rec.get("user_id") or store_key,
                "trace_id": rec.get("trace_id") or store_key,
            },
            hil_event_id=store_key,
            authored_by="human",
            skip_backtest=True,
            actor="care-webhook",
            skip_reason="fp soften",
            intent="soften",
            override_why="frontline fp",
        )
    except L2DraftError:
        return None
    if fp_cost:
        pack.setdefault("evidence", {})["fp_cost"] = fp_cost
    fname = f"l2_{uuid.uuid4().hex[:12]}.json"
    (rules_dir / fname).write_text(json.dumps(pack, indent=2), encoding="utf-8")
    try:
        from decision_api.json_rules import load_rules

        load_rules()
    except Exception:
        pass
    return {"file": fname, "pack": pack}


def _maybe_open_observe_soften(
    tenant_id: str,
    store_key: str,
    receipt: dict[str, Any] | None = None,
    fp_cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """FP on a receipt can open Observe soften work. Not a Care queue."""
    draft = _mint_soften_draft(tenant_id, receipt, store_key, fp_cost)
    try:
        from decision_api.observe_notify import (
            EVENT_CONSIDER_SOFTEN,
            emit_observe_event,
        )
    except ImportError:
        out = {
            "opened": False,
            "type": "consider_soften",
            "href": f"/ops/shadow?trace_id={store_key}",
        }
        if draft:
            out["opened"] = True
            out["draft"] = draft
        return out
    sid = (draft or {}).get("file") or store_key
    notify = emit_observe_event(
        tenant_id=tenant_id,
        event_type=EVENT_CONSIDER_SOFTEN,
        subject_id=store_key,
        draft_id=str(sid),
    )
    href = str(
        (notify.get("row") or {}).get("href") or f"/ops/shadow?trace_id={store_key}"
    )
    out = {
        "opened": bool(notify.get("created") or notify.get("id") or draft),
        "type": EVENT_CONSIDER_SOFTEN,
        "href": href,
        "id": notify.get("id"),
    }
    if draft:
        out["draft"] = draft
    return out


def join_follow_on_evaluate(
    tenant_id: str,
    *,
    entity_id: str,
    later_trace_id: str = "",
    label_kind: str = "other",
) -> dict[str, Any]:
    """One learning join: later evaluate on the same entity labels a prior receipt.

    Not a CRM case. ``label_source`` is ``evaluate``.
    """
    prior = find_prior_receipt_for_entity(
        tenant_id, entity_id, exclude_trace=later_trace_id
    )
    if prior is None:
        raise LateLabelError(
            "missing_prior_receipt",
            "no prior receipt for entity",
        )
    token = str(prior.get("trace_id") or "").strip()
    if not token:
        raise LateLabelError(
            "missing_prior_receipt",
            "prior receipt missing trace_id",
        )
    return bind_late_label(
        tenant_id,
        decision_token=token,
        label_kind=label_kind or "other",
        source="evaluate",
    )


def bind_late_label(
    tenant_id: str,
    *,
    outcome: str = "",
    trace_id: str = "",
    evaluation_token: str = "",
    decision_token: str = "",
    label_kind: str = "",
    source: str = "",
    prior_override_id: str = "",
    entity_id: str = "",
    later_trace_id: str = "",
    fp_cost: Any = None,
) -> dict[str, Any]:
    """Join late outcome onto the original receipt. Never rebuilds a graph."""
    tenant = (tenant_id or "").strip()
    if not tenant:
        raise LateLabelError("missing_tenant", "tenant_id is required")

    src_raw = (source or "").strip()
    join = (
        (decision_token or "").strip()
        or (trace_id or "").strip()
        or (evaluation_token or "").strip()
    )
    if src_raw.lower() == "evaluate" and not join:
        return join_follow_on_evaluate(
            tenant,
            entity_id=entity_id,
            later_trace_id=later_trace_id,
            label_kind=label_kind or "other",
        )
    if not join:
        raise LateLabelError(
            "missing_join_key",
            "trace_id, evaluation_token, or decision_token is required",
        )

    kind_raw = (label_kind or "").strip()
    outcome_raw = (outcome or "").strip()
    chargeback = bool(outcome_raw) and not kind_raw
    if kind_raw:
        kind = normalize_label_kind(kind_raw)
        y = y_label_for_kind(kind)
        token = ""
    elif outcome_raw:
        token = normalize_outcome(outcome_raw)
        y = y_label_for_outcome(token)
        kind = "fraud" if token == "FRAUD" else "other"
    else:
        raise LateLabelError(
            "missing_label",
            "label_kind or dispute.outcome is required",
        )

    if src_raw:
        src = normalize_source(src_raw)
    else:
        src = "finance" if chargeback or kind == "fraud" else "care"

    override_id = (prior_override_id or "").strip()
    receipt = None
    if override_id:
        receipt = find_override_receipt(tenant, override_id, join)
    if receipt is None:
        receipt = find_receipt(tenant, join)
    store_key = (
        str(receipt.get("trace_id") or "").strip() if isinstance(receipt, dict) else ""
    ) or join

    kind_map = {store_key: kind}
    src_map = {store_key: src}
    ovr_map = {store_key: override_id} if override_id else None
    disp_map = {store_key: token} if chargeback and token else None
    cls_map = {store_key: token} if chargeback and token else None
    parsed_cost = parse_fp_cost(fp_cost) if kind == "fp" else None
    cost_map = None
    if parsed_cost:
        cost_map = {store_key: json.dumps(parsed_cost, sort_keys=True, default=str)}
    labeled_at = datetime.now(timezone.utc).isoformat()
    merge_y_labels(
        tenant,
        by_trace={store_key: y},
        dispute_outcome_by_trace=disp_map,
        chargeback_class_by_trace=cls_map,
        label_kind_by_trace=kind_map,
        label_source_by_trace=src_map,
        prior_override_id_by_trace=ovr_map,
        fp_cost_by_trace=cost_map,
        labeled_at_by_trace={store_key: labeled_at},
    )

    observe: dict[str, Any] = {"opened": False}
    fp_cost: dict[str, Any] | None = None
    if kind == "fp":
        decision = (
            str(receipt.get("decision") or "").strip()
            if isinstance(receipt, dict)
            else ""
        )
        fp_cost = {
            "counted": True,
            "decision": decision,
            "restrictive": decision.lower() in RESTRICTIVE_DECISIONS
            if decision
            else True,
            "rule_hits": _hits_of(receipt),
        }
        if parsed_cost:
            fp_cost.update(parsed_cost)
        observe = _maybe_open_observe_soften(
            tenant,
            store_key,
            receipt if isinstance(receipt, dict) else None,
            fp_cost,
        )

    out: dict[str, Any] = {
        "ok": True,
        "schema_id": SCHEMA_ID,
        "tenant_id": tenant,
        "trace_id": store_key,
        "decision_token": store_key,
        "label_kind": kind,
        "label_source": src,
        "y_label": y,
        "snapshot_bound": receipt is not None,
        "trainable": receipt is not None and bool(_edges_of(receipt)),
        "observe_work": observe,
    }
    if override_id:
        out["prior_override_id"] = override_id
    if chargeback and token:
        out["dispute_outcome"] = token
        out["chargeback_class"] = token
    else:
        out["dispute_outcome"] = ""
        out["chargeback_class"] = ""
    if fp_cost is not None:
        out["fp_cost"] = fp_cost
    return out
