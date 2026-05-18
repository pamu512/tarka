from __future__ import annotations

from typing import Any

from investigation_agent import batch_store
from investigation_agent.tools import (
    _coerce_replay_trace_ids,
    _validate_case_id,
    _validate_dataset_limit,
    _validate_depth,
    _validate_entity_id,
    _validate_limit,
    _validate_max_velocity_nodes,
    _validate_replay_limit,
    _validate_subject_name,
    _validate_trace_id,
)

"""Validate LLM tool-call arguments before dispatch (no KeyError, structured errors)."""


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes")
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def validate_tool_arguments(name: str, raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    """
    Return (normalized_args, None) or (None, error_message).
    Normalized dict contains only keys the tool implementation expects.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return None, "tool arguments must be a JSON object"

    if name == "get_case":
        cid = raw.get("case_id")
        if cid is None or (isinstance(cid, str) and not cid.strip()):
            return None, "get_case requires non-empty case_id"
        try:
            return {"case_id": _validate_case_id(str(cid))}, None
        except ValueError:
            return None, "invalid case_id"

    if name == "list_cases":
        lim = raw.get("limit", 20)
        try:
            lim_i = int(lim)
        except (TypeError, ValueError):
            return None, "limit must be an integer"
        return {"limit": _validate_limit(lim_i)}, None

    if name in ("subgraph", "get_entity_tags", "get_entity_velocity"):
        eid = raw.get("entity_id")
        if eid is None or (isinstance(eid, str) and not str(eid).strip()):
            return None, f"{name} requires non-empty entity_id"
        try:
            eid_v = _validate_entity_id(str(eid))
        except ValueError:
            return None, "invalid entity_id"
        if name != "subgraph":
            return {"entity_id": eid_v}, None
        d = raw.get("depth", 2)
        try:
            di = int(d)
        except (TypeError, ValueError):
            return None, "depth must be an integer"
        return {"entity_id": eid_v, "depth": _validate_depth(di)}, None

    if name == "get_decision_audit":
        tid = raw.get("trace_id")
        if tid is None or (isinstance(tid, str) and not str(tid).strip()):
            return None, "get_decision_audit requires trace_id"
        try:
            return {"trace_id": _validate_trace_id(str(tid).strip())}, None
        except ValueError:
            return None, "invalid trace_id"

    if name == "subgraph_with_velocity":
        eid = raw.get("entity_id")
        if eid is None or (isinstance(eid, str) and not str(eid).strip()):
            return None, "subgraph_with_velocity requires entity_id"
        try:
            eid_v = _validate_entity_id(str(eid))
        except ValueError:
            return None, "invalid entity_id"
        d = raw.get("depth", 2)
        try:
            di = int(d)
        except (TypeError, ValueError):
            return None, "depth must be an integer"
        mn = raw.get("max_velocity_nodes", 10)
        try:
            mi = int(mn)
        except (TypeError, ValueError):
            return None, "max_velocity_nodes must be an integer"
        return {
            "entity_id": eid_v,
            "depth": _validate_depth(di),
            "max_velocity_nodes": _validate_max_velocity_nodes(mi),
        }, None

    if name == "export_outcome_labeled_dataset":
        cl = raw.get("case_limit", 50)
        dl = raw.get("dispute_limit", 50)
        try:
            ci = int(cl)
        except (TypeError, ValueError):
            return None, "case_limit must be an integer"
        try:
            di = int(dl)
        except (TypeError, ValueError):
            return None, "dispute_limit must be an integer"
        return {
            "case_limit": _validate_dataset_limit(ci),
            "dispute_limit": _validate_dataset_limit(di),
            "resolved_disputes_only": _as_bool(raw.get("resolved_disputes_only", True), True),
        }, None

    if name == "ingest_labeled_rows":
        rows = raw.get("rows")
        if rows is None:
            return None, "ingest_labeled_rows requires rows"
        if not isinstance(rows, list):
            return None, "rows must be an array"
        return {
            "rows": rows,
            "clear_existing": _as_bool(raw.get("clear_existing", False), False),
        }, None

    if name == "get_stored_labeled_dataset":
        return {}, None

    if name == "get_batch_profile":
        bid = raw.get("batch_id")
        if bid is None or (isinstance(bid, str) and not str(bid).strip()):
            return None, "get_batch_profile requires batch_id"
        try:
            return {"batch_id": batch_store.validate_batch_id(str(bid))}, None
        except ValueError as e:
            return None, "invalid tool arguments"

    if name == "query_batch_rows":
        bid = raw.get("batch_id")
        if bid is None or (isinstance(bid, str) and not str(bid).strip()):
            return None, "query_batch_rows requires batch_id"
        try:
            bid_v = batch_store.validate_batch_id(str(bid))
        except ValueError as e:
            return None, "invalid tool arguments"
        off = raw.get("offset", 0)
        lim = raw.get("limit", 25)
        try:
            oi = int(off)
            li = int(lim)
        except (TypeError, ValueError):
            return None, "offset and limit must be integers"
        cols = raw.get("columns")
        if cols is not None and not isinstance(cols, list):
            return None, "columns must be an array or omitted"
        col_list = [str(c).strip() for c in cols if str(c).strip()][:128] if isinstance(cols, list) else None
        return {
            "batch_id": bid_v,
            "offset": max(0, oi),
            "limit": max(1, min(li, 100)),
            "columns": col_list,
        }, None

    if name == "aggregate_batch_column":
        bid = raw.get("batch_id")
        col = raw.get("column")
        if bid is None or (isinstance(bid, str) and not str(bid).strip()):
            return None, "aggregate_batch_column requires batch_id"
        if col is None or (isinstance(col, str) and not str(col).strip()):
            return None, "aggregate_batch_column requires column"
        try:
            bid_v = batch_store.validate_batch_id(str(bid))
        except ValueError as e:
            return None, "invalid tool arguments"
        mode = str(raw.get("mode", "value_counts") or "value_counts").lower()
        if mode not in ("value_counts", "numeric_summary"):
            return None, "mode must be value_counts or numeric_summary"
        return {"batch_id": bid_v, "column": str(col).strip()[:256], "mode": mode}, None

    if name == "run_replay_ab_comparison":
        a = raw.get("rules_variant_a")
        b = raw.get("rules_variant_b")
        if not isinstance(a, list):
            return None, "rules_variant_a must be an array"
        if not isinstance(b, list):
            return None, "rules_variant_b must be an array"
        lim = raw.get("limit", 80)
        try:
            li = int(lim)
        except (TypeError, ValueError):
            return None, "limit must be an integer"
        trace_ids = raw.get("trace_ids")
        if trace_ids is not None and not isinstance(trace_ids, list):
            return None, "trace_ids must be an array or omitted"
        tid_list, tid_err = _coerce_replay_trace_ids(trace_ids)
        if tid_err:
            return None, tid_err
        return {
            "rules_variant_a": a,
            "rules_variant_b": b,
            "limit": _validate_replay_limit(li),
            "trace_ids": tid_list,
        }, None

    if name == "search_knowledge":
        q = raw.get("query")
        if q is None or (isinstance(q, str) and not str(q).strip()):
            return None, "search_knowledge requires query"
        lim = raw.get("limit", 5)
        try:
            li = int(lim)
        except (TypeError, ValueError):
            return None, "limit must be an integer"
        return {"query": str(q).strip()[:512], "limit": max(1, min(li, 15))}, None

    if name == "compare_entity_queue_snapshot":
        eid = raw.get("entity_id")
        if eid is None or (isinstance(eid, str) and not str(eid).strip()):
            return None, "compare_entity_queue_snapshot requires entity_id"
        try:
            eid_v = _validate_entity_id(str(eid))
        except ValueError as e:
            return None, "invalid tool arguments"
        ll = raw.get("list_limit", 80)
        try:
            li = int(ll)
        except (TypeError, ValueError):
            return None, "list_limit must be an integer"
        return {"entity_id": eid_v, "list_limit": max(10, min(li, 100))}, None

    if name in ("screen_sanctions_pep", "summarize_adverse_media", "consolidate_entity_profile"):
        q_name = raw.get("name")
        if q_name is None or (isinstance(q_name, str) and not str(q_name).strip()):
            return None, f"{name} requires name"
        try:
            q_name_v = _validate_subject_name(str(q_name))
        except ValueError as e:
            return None, "invalid tool arguments"
        out = {
            "name": q_name_v,
            "subject_id": str(raw.get("subject_id", "")).strip()[:128] or None,
            "country": str(raw.get("country", "")).strip()[:8] or None,
            "dob": str(raw.get("dob", "")).strip()[:32] or None,
            "email": str(raw.get("email", "")).strip()[:256] or None,
            "phone": str(raw.get("phone", "")).strip()[:64] or None,
            "ip": str(raw.get("ip", "")).strip()[:64] or None,
            "domain": str(raw.get("domain", "")).strip()[:256] or None,
        }
        if name == "screen_sanctions_pep":
            return {
                "name": out["name"],
                "subject_id": out["subject_id"],
                "country": out["country"],
                "dob": out["dob"],
            }, None
        if name == "summarize_adverse_media":
            return {
                "name": out["name"],
                "subject_id": out["subject_id"],
                "email": out["email"],
                "phone": out["phone"],
                "ip": out["ip"],
                "domain": out["domain"],
            }, None
        return {
            **out,
            "include_profile_enrichment": _as_bool(raw.get("include_profile_enrichment", True), True),
        }, None

    if name == "graph_risk_narrative":
        eid = raw.get("entity_id")
        if eid is None or (isinstance(eid, str) and not str(eid).strip()):
            return None, "graph_risk_narrative requires entity_id"
        try:
            eid_v = _validate_entity_id(str(eid))
        except ValueError as e:
            return None, "invalid tool arguments"
        try:
            depth = int(raw.get("depth", 2))
            max_nodes = int(raw.get("max_velocity_nodes", 10))
        except (TypeError, ValueError):
            return None, "depth and max_velocity_nodes must be integers"
        return {
            "entity_id": eid_v,
            "depth": _validate_depth(depth),
            "max_velocity_nodes": _validate_max_velocity_nodes(max_nodes),
        }, None

    return None, f"unknown tool for validation: {name}"
