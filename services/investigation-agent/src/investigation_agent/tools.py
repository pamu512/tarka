"""Tool definitions and execution for the investigation agent."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from investigation_agent import batch_store, knowledge_store
from investigation_agent.config import settings

_MAX_RULES_OVERRIDE = 15
_MAX_REPLAY_TRACE_IDS = 150
_MAX_CONDITIONS_PER_RULE = 12
_VALID_REPLAY_OPS = frozenset(
    {
        "eq",
        "not_eq",
        "gte",
        "gt",
        "lte",
        "lt",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        "regex",
        "is_true",
        "is_false",
        "exists",
        "not_exists",
    }
)

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._@:/-]{1,256}$")


def _validate_case_id(case_id: str) -> str:
    """Validate case_id as UUID or safe identifier."""
    case_id = str(case_id).strip()
    if not (_UUID_PATTERN.match(case_id) or _SAFE_ID_PATTERN.match(case_id)):
        raise ValueError(f"Invalid case_id format: {case_id[:50]}")
    return case_id


def _validate_entity_id(entity_id: str) -> str:
    """Validate entity_id contains only safe characters."""
    entity_id = str(entity_id).strip()[:256]
    if not _SAFE_ID_PATTERN.match(entity_id):
        raise ValueError("Invalid entity_id format")
    return entity_id


def _validate_limit(limit: int) -> int:
    """Clamp limit to safe range."""
    return max(1, min(int(limit), 100))


def _validate_depth(depth: int) -> int:
    """Clamp graph depth to safe range."""
    return max(1, min(int(depth), 5))


def _validate_trace_id(trace_id: str) -> str:
    tid = str(trace_id).strip()
    if not _UUID_PATTERN.match(tid):
        raise ValueError("Invalid trace_id (expected UUID)")
    return tid


def _validate_max_velocity_nodes(n: int) -> int:
    return max(1, min(int(n), 20))


def _validate_replay_limit(limit: int) -> int:
    return max(1, min(int(limit), 150))


def _validate_dataset_limit(limit: int) -> int:
    return max(1, min(int(limit), 100))


def _coerce_replay_trace_ids(raw: Any) -> tuple[list[str] | None, str | None]:
    """Return (trace_ids for replay body, error_message). Empty list input → use limit mode (None)."""
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, "trace_ids must be a list"
    parsed: list[str] = []
    for x in raw[:_MAX_REPLAY_TRACE_IDS]:
        try:
            parsed.append(_validate_trace_id(str(x).strip()))
        except ValueError:
            continue
    if len(raw) > 0 and not parsed:
        return None, "trace_ids contained no valid UUIDs"
    return (parsed if parsed else None), None


def _sanitize_rules_override(raw: Any) -> list[dict[str, Any]]:
    """Clamp rules_override for POST /v1/replay (size and shape bounds)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for r in raw[:_MAX_RULES_OVERRIDE]:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id", "") or "anon")[:64]
        if not re.match(r"^[a-zA-Z0-9._:@/-]*$", rid):
            rid = "anon"
        when_in = r.get("when") or []
        if not isinstance(when_in, list):
            continue
        when_out: list[dict[str, Any]] = []
        for c in when_in[:_MAX_CONDITIONS_PER_RULE]:
            if not isinstance(c, dict):
                continue
            field = str(c.get("field", ""))[:128]
            if not field or not re.match(r"^[a-zA-Z0-9._@-]+$", field):
                continue
            op = str(c.get("op", "eq") or "eq")
            if op not in _VALID_REPLAY_OPS:
                continue
            when_out.append({"field": field, "op": op, "value": c.get("value")})
        if not when_out:
            continue
        tags_in = r.get("tags") or []
        tags: list[str] = []
        if isinstance(tags_in, list):
            for t in tags_in[:20]:
                ts = str(t)[:64]
                if ts and re.match(r"^[a-zA-Z0-9._:@/-]+$", ts):
                    tags.append(ts)
        try:
            sd = float(r.get("score_delta", 0))
        except (TypeError, ValueError):
            sd = 0.0
        sd = max(-50.0, min(50.0, sd))
        desc = str(r.get("description", ""))[:256]
        out.append({"id": rid, "when": when_out, "tags": tags, "score_delta": sd, "description": desc})
    return out


def _case_labels_to_y(labels: list[str] | None) -> tuple[str, str]:
    """Map case labels to (y_label, note)."""
    s = set(labels or [])
    if "confirmed_fraud" in s:
        return "fraud", "case label confirmed_fraud"
    if "false_positive" in s or "dispute:false_positive" in s:
        return "legitimate", "case label false_positive / dispute:false_positive"
    return "unknown", "no definitive fraud/fp case labels"


def _dispute_outcome_to_y(outcome: str | None) -> tuple[str, str]:
    if not outcome:
        return "unknown", "no outcome"
    if outcome == "fraud_confirmed":
        return "fraud", "dispute outcome fraud_confirmed"
    if outcome == "false_positive":
        return "legitimate", "dispute outcome false_positive"
    if outcome == "merchant_fault":
        return "fraud", "dispute outcome merchant_fault (chargeback upheld)"
    if outcome == "customer_fault":
        return "legitimate", "dispute outcome customer_fault"
    if outcome == "inconclusive":
        return "unknown", "dispute outcome inconclusive"
    return "unknown", f"outcome {outcome}"


def _limit_result(result: Any, max_chars: int = 6000) -> dict:
    """Ensure tool results don't overflow the context window."""
    s = json.dumps(result, default=str)
    if len(s) <= max_chars:
        return result
    if isinstance(result, dict):
        trimmed = {}
        for k, v in result.items():
            if isinstance(v, list) and len(v) > 10:
                trimmed[k] = v[:10]
                trimmed[f"{k}_truncated"] = True
                trimmed[f"{k}_total"] = len(v)
            else:
                trimmed[k] = v
        return trimmed
    return result


def _auth_headers() -> dict[str, str]:
    if settings.upstream_api_key:
        return {"x-api-key": settings.upstream_api_key}
    return {}


# ---------- RBAC ----------


def _analyst_allowed(analyst_id: str) -> bool:
    raw = (settings.allowed_analysts or "*").strip()
    if raw == "*":
        return True
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return analyst_id in allowed


def is_analyst_allowed(analyst_id: str) -> bool:
    """Used by HTTP layer before running LLM / tools."""
    return _analyst_allowed(analyst_id)


# ---------- Tool implementations ----------


async def tool_get_case(http: httpx.AsyncClient, case_id: str, tenant_id: str, analyst_id: str) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        case_id = _validate_case_id(case_id)
    except ValueError as e:
        return {"error": str(e)}
    base = settings.case_api_url.rstrip("/")
    r = await http.get(
        f"{base}/v1/cases/{case_id}",
        params={"tenant_id": tenant_id},
        headers=_auth_headers(),
    )
    if r.status_code == 404:
        return {"error": "not_found"}
    r.raise_for_status()
    return _limit_result({"case": r.json()})


async def tool_list_cases(http: httpx.AsyncClient, tenant_id: str, analyst_id: str, limit: int = 20) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    limit = _validate_limit(limit)
    base = settings.case_api_url.rstrip("/")
    r = await http.get(f"{base}/v1/cases", params={"tenant_id": tenant_id, "limit": limit}, headers=_auth_headers())
    r.raise_for_status()
    return _limit_result(r.json())


async def tool_subgraph(
    http: httpx.AsyncClient,
    entity_id: str,
    tenant_id: str,
    analyst_id: str,
    depth: int = 2,
) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        entity_id = _validate_entity_id(entity_id)
    except ValueError as e:
        return {"error": str(e)}
    depth = _validate_depth(depth)
    if not settings.graph_service_url:
        return {"error": "graph_disabled"}
    base = settings.graph_service_url.rstrip("/")
    r = await http.get(
        f"{base}/v1/subgraph",
        params={"entity_id": entity_id, "tenant_id": tenant_id, "depth": depth},
        headers=_auth_headers(),
    )
    r.raise_for_status()
    return _limit_result(r.json())


async def tool_get_entity_tags(
    http: httpx.AsyncClient,
    entity_id: str,
    tenant_id: str,
    analyst_id: str,
) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        entity_id = _validate_entity_id(entity_id)
    except ValueError as e:
        return {"error": str(e)}
    if not settings.graph_service_url:
        return {"error": "graph_disabled"}
    base = settings.graph_service_url.rstrip("/")
    r = await http.get(f"{base}/v1/entities/{entity_id}/tags", params={"tenant_id": tenant_id}, headers=_auth_headers())
    r.raise_for_status()
    return _limit_result(r.json())


async def tool_get_entity_velocity(http: httpx.AsyncClient, entity_id: str, tenant_id: str, analyst_id: str) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        entity_id = _validate_entity_id(entity_id)
    except ValueError as e:
        return {"error": str(e)}
    base = (settings.decision_api_url or "").rstrip("/")
    if not base:
        return {"error": "decision_api_disabled"}
    r = await http.get(
        f"{base}/v1/analyst/entity-velocity",
        params={"tenant_id": tenant_id, "entity_id": entity_id},
        headers=_auth_headers(),
    )
    if r.status_code == 400:
        return {"error": "bad_request", "detail": r.text[:500]}
    r.raise_for_status()
    return _limit_result(r.json())


async def tool_get_decision_audit(http: httpx.AsyncClient, trace_id: str, tenant_id: str, analyst_id: str) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        trace_id = _validate_trace_id(trace_id)
    except ValueError as e:
        return {"error": str(e)}
    base = (settings.decision_api_url or "").rstrip("/")
    if not base:
        return {"error": "decision_api_disabled"}
    r = await http.get(
        f"{base}/v1/audit/{trace_id}",
        params={"tenant_id": tenant_id},
        headers=_auth_headers(),
    )
    if r.status_code == 404:
        return {"error": "not_found"}
    r.raise_for_status()
    return _limit_result({"audit": r.json()})


async def tool_subgraph_with_velocity(
    http: httpx.AsyncClient,
    entity_id: str,
    tenant_id: str,
    analyst_id: str,
    depth: int = 2,
    max_velocity_nodes: int = 10,
) -> dict[str, Any]:
    """Subgraph plus per-node velocity aggregates and inference slice (bounded)."""
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    sg = await tool_subgraph(http, entity_id, tenant_id, analyst_id, depth)
    if sg.get("error"):
        return sg
    base = (settings.decision_api_url or "").rstrip("/")
    if not base:
        return {**sg, "note": "decision_api_url not set; graph only, no velocity overlay"}
    max_n = _validate_max_velocity_nodes(max_velocity_nodes)
    nodes = list(sg.get("nodes") or [])
    enriched: list[dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if i >= max_n:
            enriched.append(n)
            continue
        eid = (n.get("id") or (n.get("properties") or {}).get("external_id") or "").strip()
        if not eid:
            enriched.append(n)
            continue
        try:
            _validate_entity_id(eid)
        except ValueError:
            enriched.append(n)
            continue
        try:
            vr = await http.get(
                f"{base}/v1/analyst/entity-velocity",
                params={"tenant_id": tenant_id, "entity_id": eid},
                headers=_auth_headers(),
            )
            if vr.status_code == 200:
                props = n.get("properties") or {}
                sdk_hint = {
                    k: props[k]
                    for k in (
                        "is_vpn",
                        "is_emulator",
                        "is_bot",
                        "is_proxy",
                        "ip_is_datacenter",
                        "ip_is_proxy",
                        "automation_detected",
                        "headless_detected",
                        "webdriver_detected",
                    )
                    if k in props
                }
                enriched.append(
                    {
                        **n,
                        "velocity_and_inference": vr.json(),
                        "sdk_signals_on_node": sdk_hint if sdk_hint else None,
                    }
                )
            else:
                enriched.append(n)
        except Exception:
            enriched.append(n)
    return _limit_result({"nodes": enriched, "edges": sg.get("edges", []), "center_entity_id": entity_id})


async def tool_export_outcome_labeled_dataset(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    case_limit: int = 50,
    dispute_limit: int = 50,
    resolved_disputes_only: bool = True,
) -> dict[str, Any]:
    """Build a weakly-labeled dataset from case labels and resolved dispute outcomes."""
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    cl = _validate_dataset_limit(case_limit)
    dl = _validate_dataset_limit(dispute_limit)
    base = settings.case_api_url.rstrip("/")
    headers = _auth_headers()
    rows: list[dict[str, Any]] = []
    by_trace: dict[str, dict[str, Any]] = {}

    try:
        cr = await http.get(
            f"{base}/v1/cases",
            params={"tenant_id": tenant_id, "limit": cl, "sort_by": "updated"},
            headers=headers,
        )
        cr.raise_for_status()
        for c in (cr.json().get("items") or [])[:cl]:
            if not isinstance(c, dict):
                continue
            y, note = _case_labels_to_y(c.get("labels"))
            if y == "unknown":
                continue
            tid = str(c.get("trace_id") or "").strip()
            eid = str(c.get("entity_id") or "").strip()
            row = {
                "source": "case",
                "case_id": str(c.get("id", "")),
                "entity_id": eid,
                "trace_id": tid or None,
                "y_label": y,
                "label_note": note,
            }
            if tid:
                by_trace[tid] = row
            else:
                rows.append(row)
    except Exception as e:
        return {"error": "cases_fetch_failed", "detail": str(e)[:500]}

    try:
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": dl}
        if resolved_disputes_only:
            params["status"] = "resolved"
        dr = await http.get(f"{base}/v1/disputes", params=params, headers=headers)
        dr.raise_for_status()
        for d in (dr.json().get("items") or [])[:dl]:
            if not isinstance(d, dict):
                continue
            outcome = d.get("outcome")
            if resolved_disputes_only and not outcome:
                continue
            y, note = _dispute_outcome_to_y(outcome if isinstance(outcome, str) else None)
            if y == "unknown" and resolved_disputes_only:
                continue
            tid = str(d.get("trace_id") or "").strip()
            row = {
                "source": "dispute",
                "dispute_id": str(d.get("id", "")),
                "case_id": str(d.get("case_id") or "") if d.get("case_id") else None,
                "entity_id": str(d.get("entity_id") or ""),
                "trace_id": tid or None,
                "y_label": y,
                "label_note": note,
                "dispute_status": d.get("status"),
            }
            if tid:
                by_trace[tid] = row
            else:
                rows.append(row)
    except Exception as e:
        return {"error": "disputes_fetch_failed", "detail": str(e)[:500]}

    merged = list(by_trace.values()) + rows
    counts: dict[str, int] = {}
    for r in merged:
        y = r.get("y_label", "unknown")
        counts[y] = counts.get(y, 0) + 1
    return _limit_result(
        {
            "tenant_id": tenant_id,
            "items": merged,
            "total": len(merged),
            "counts_by_y_label": counts,
            "caveat": (
                "Labels are operational weak ground truth: case tags and dispute outcomes can be noisy, "
                "delayed, or jurisdiction-specific. Prefer replay A/B on recent audits for causal rule comparison."
            ),
        }
    )


async def tool_ingest_labeled_rows(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    rows: list[dict[str, Any]],
    clear_existing: bool = False,
) -> dict[str, Any]:
    """Persist analyst label drafts via case-api (tenant + analyst scoped, durable)."""
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    if not isinstance(rows, list):
        return {"error": "rows must be a list"}
    valid_labels = frozenset({"fraud", "legitimate", "unknown"})
    api_rows: list[dict[str, Any]] = []
    for raw in rows[:50]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("y_label") or "").strip().lower()
        if label not in valid_labels:
            continue
        trace_id = raw.get("trace_id")
        entity_id = raw.get("entity_id")
        tid = str(trace_id).strip() if trace_id else ""
        eid = str(entity_id).strip()[:512] if entity_id else ""
        if tid:
            try:
                tid = _validate_trace_id(tid)
            except ValueError:
                continue
        elif not eid:
            continue
        if eid:
            try:
                eid = _validate_entity_id(eid)
            except ValueError:
                continue
        notes = raw.get("notes")
        api_rows.append(
            {
                "trace_id": tid or None,
                "entity_id": eid or None,
                "y_label": label,
                "source": str(raw.get("source") or "analyst")[:128],
                "notes": str(notes)[:4000] if notes is not None else None,
            }
        )
    base = settings.case_api_url.rstrip("/")
    try:
        r = await http.post(
            f"{base}/v1/investigation-label-drafts/batch",
            params={"tenant_id": tenant_id},
            json={
                "analyst_id": analyst_id,
                "rows": api_rows,
                "clear_existing": clear_existing,
            },
            headers=_auth_headers(),
        )
        if r.status_code >= 400:
            return {"error": "label_drafts_batch_failed", "status": r.status_code, "detail": r.text[:500]}
        return _limit_result({**r.json(), "storage": "case_api_investigation_label_drafts"})
    except Exception as e:
        return {"error": "label_drafts_batch_failed", "detail": str(e)[:500]}


async def tool_get_stored_labeled_dataset(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    base = settings.case_api_url.rstrip("/")
    try:
        r = await http.get(
            f"{base}/v1/investigation-label-drafts",
            params={"tenant_id": tenant_id, "analyst_id": analyst_id, "limit": 200},
            headers=_auth_headers(),
        )
        if r.status_code >= 400:
            return {"error": "label_drafts_list_failed", "status": r.status_code, "detail": r.text[:500]}
        data = r.json()
        items = data.get("items") or []
        normalized = [
            {
                "id": str(x.get("id", "")),
                "trace_id": x.get("trace_id"),
                "entity_id": x.get("entity_id"),
                "y_label": x.get("y_label"),
                "source": x.get("source"),
                "notes": x.get("notes"),
            }
            for x in items
            if isinstance(x, dict)
        ]
        return _limit_result(
            {
                "items": normalized,
                "total": len(normalized),
                "storage": "case_api_investigation_label_drafts",
            }
        )
    except Exception as e:
        return {"error": "label_drafts_list_failed", "detail": str(e)[:500]}


def _paired_replay_comparison(va: dict[str, Any], vb: dict[str, Any]) -> dict[str, Any]:
    ra = {str(x.get("trace_id")): x for x in (va.get("results") or []) if x.get("trace_id")}
    rb = {str(x.get("trace_id")): x for x in (vb.get("results") or []) if x.get("trace_id")}
    common = sorted(set(ra) & set(rb))
    disagree: list[dict[str, Any]] = []
    for tid in common:
        a_changed = bool(ra[tid].get("decision_changed"))
        b_changed = bool(rb[tid].get("decision_changed"))
        if a_changed != b_changed:
            disagree.append(
                {
                    "trace_id": tid,
                    "variant_a_changed": a_changed,
                    "variant_b_changed": b_changed,
                }
            )
    return {
        "paired_traces": len(common),
        "traces_where_flip_differs_between_variants": len(disagree),
        "sample_flip_disagreements": disagree[:8],
    }


async def tool_run_replay_ab_comparison(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    rules_variant_a: list[dict[str, Any]],
    rules_variant_b: list[dict[str, Any]],
    limit: int = 80,
    trace_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run decision-api replay twice with two rule overrides; optional paired trace_ids set."""
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    base = (settings.decision_api_url or "").rstrip("/")
    if not base:
        return {"error": "decision_api_disabled"}
    ra = _sanitize_rules_override(rules_variant_a)
    rb = _sanitize_rules_override(rules_variant_b)
    if not ra or not rb:
        return {
            "error": ("both rules_variant_a and rules_variant_b must contain at least one valid rule after sanitization"),
        }
    lim = _validate_replay_limit(limit)
    tid_list, tid_err = _coerce_replay_trace_ids(trace_ids)
    if tid_err:
        return {"error": tid_err}
    headers = {**_auth_headers(), "Content-Type": "application/json"}

    async def _post(rules: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {"tenant_id": tenant_id, "rules_override": rules, "limit": lim}
        if tid_list:
            body["trace_ids"] = tid_list
        r = await http.post(f"{base}/v1/replay", json=body, headers=headers)
        if r.status_code == 404:
            return {"error": "no_audit_records", "detail": r.text[:300]}
        if r.status_code >= 400:
            return {"error": "replay_failed", "status": r.status_code, "detail": r.text[:500]}
        return r.json()

    va = await _post(ra)
    if va.get("error"):
        return {"variant_a": va, "variant_b": None, "comparison": None, "trace_ids_mode": bool(tid_list)}
    vb = await _post(rb)
    if vb.get("error"):
        return {"variant_a": _replay_summary(va), "variant_b": vb, "comparison": None, "trace_ids_mode": bool(tid_list)}

    sa = _replay_summary(va)
    sb = _replay_summary(vb)
    dca = int(va.get("decisions_changed") or 0)
    dcb = int(vb.get("decisions_changed") or 0)
    ev = int(va.get("events_evaluated") or 0)
    missing_a = va.get("missing_trace_ids") or []
    missing_b = vb.get("missing_trace_ids") or []
    paired_extra = _paired_replay_comparison(va, vb) if tid_list else {}
    if tid_list:
        caveat = (
            "Paired replay: both variants evaluated the same trace_ids list (order preserved). "
            "Check missing_trace_ids if some UUIDs had no audit row for this tenant."
        )
    else:
        caveat = (
            "Two sequential replays over the same limit; newest-audit window may shift slightly between calls. "
            "Prefer passing trace_ids (from label drafts or audits) for paired comparison."
        )
    return _limit_result(
        {
            "variant_a": sa,
            "variant_b": sb,
            "comparison": {
                "events_evaluated": ev,
                "decisions_changed_a": dca,
                "decisions_changed_b": dcb,
                "delta_decisions_changed": dcb - dca,
                "missing_trace_ids_a": missing_a,
                "missing_trace_ids_b": missing_b,
                "caveat": caveat,
                **paired_extra,
            },
            "rules_sent_a": ra,
            "rules_sent_b": rb,
            "trace_ids_mode": bool(tid_list),
        }
    )


async def tool_get_batch_profile(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    batch_id: str,
) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        bid = batch_store.validate_batch_id(batch_id)
    except ValueError as e:
        return {"error": str(e)}
    rec = batch_store.get_batch(bid, tenant_id, analyst_id)
    if not rec:
        return {"error": "batch_not_found", "detail": "Upload via POST /v1/batch/ingest or check batch_id / tenant."}
    prof = batch_store.batch_profile(rec)
    return _limit_result(prof)


async def tool_query_batch_rows(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    batch_id: str,
    offset: int = 0,
    limit: int = 25,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        bid = batch_store.validate_batch_id(batch_id)
    except ValueError as e:
        return {"error": str(e)}
    rec = batch_store.get_batch(bid, tenant_id, analyst_id)
    if not rec:
        return {"error": "batch_not_found"}
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    cols = columns if isinstance(columns, list) else None
    return _limit_result(batch_store.batch_query_rows(rec, off, lim, cols))


async def tool_aggregate_batch_column(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    batch_id: str,
    column: str,
    mode: str = "value_counts",
) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        bid = batch_store.validate_batch_id(batch_id)
    except ValueError as e:
        return {"error": str(e)}
    rec = batch_store.get_batch(bid, tenant_id, analyst_id)
    if not rec:
        return {"error": "batch_not_found"}
    col = str(column).strip()
    if not col:
        return {"error": "column required"}
    m = str(mode or "value_counts").strip().lower()
    if m not in ("value_counts", "numeric_summary"):
        return {"error": "invalid_mode", "allowed": ["value_counts", "numeric_summary"]}
    return _limit_result(batch_store.batch_aggregate_column(rec, col, m))


async def tool_search_knowledge(
    http: httpx.AsyncClient,
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Keyword search over analyst-ingested investigation memos (tenant scoped)."""
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    q = str(query or "").strip()
    if not q:
        return {"error": "query required"}
    lim = max(1, min(int(limit or 5), 15))
    use_emb = settings.copilot_knowledge_embeddings and bool(settings.openai_api_key)
    data = await knowledge_store.search_async(
        http,
        use_embeddings=use_emb,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        embed_model=settings.copilot_embedding_model,
        tenant_id=tenant_id,
        analyst_id=analyst_id,
        query=q,
        limit=lim,
        keyword_weight=settings.copilot_rag_keyword_weight,
    )
    return _limit_result(data)


async def tool_compare_entity_queue_snapshot(
    http: httpx.AsyncClient,
    entity_id: str,
    tenant_id: str,
    analyst_id: str,
    list_limit: int = 80,
) -> dict[str, Any]:
    """
    Deterministic snapshot: entity velocity + count of queue cases mentioning this entity_id
    (from list_cases payload; does not scan full case database).
    """
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        eid = _validate_entity_id(str(entity_id))
    except ValueError as e:
        return {"error": str(e)}
    lim = max(10, min(int(list_limit or 80), 100))
    vel = await tool_get_entity_velocity(http, eid, tenant_id, analyst_id)
    if isinstance(vel, dict) and vel.get("error"):
        velocity_block = vel
    else:
        velocity_block = vel
    qc = await tool_list_cases(http, tenant_id, analyst_id, lim)
    if isinstance(qc, dict) and qc.get("error"):
        return {"error": "list_cases_failed", "detail": qc.get("error"), "entity_id": eid, "velocity": velocity_block}
    cases = qc.get("items") if isinstance(qc, dict) else None
    if not isinstance(cases, list):
        cases = qc.get("cases") if isinstance(qc, dict) else None
    if not isinstance(cases, list):
        cases = []
    matching: list[dict[str, Any]] = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        ce = str(c.get("entity_id") or c.get("entityId") or "")
        if ce == eid:
            matching.append(
                {
                    "case_id": c.get("id"),
                    "status": c.get("status"),
                    "priority": c.get("priority"),
                    "trace_id": c.get("trace_id"),
                },
            )
    return _limit_result(
        {
            "entity_id": eid,
            "velocity": velocity_block,
            "list_cases_limit": lim,
            "matching_open_or_recent_cases": len(matching),
            "matching_case_sample": matching[:15],
            "note": "Only cases returned by list_cases(limit) are scanned; not exhaustive.",
        },
    )


def _replay_summary(resp: dict[str, Any]) -> dict[str, Any]:
    changed = [x for x in (resp.get("results") or []) if x.get("decision_changed")]
    return {
        "events_evaluated": resp.get("events_evaluated"),
        "decisions_changed": resp.get("decisions_changed"),
        "tenant_id": resp.get("tenant_id"),
        "sample_changed": [
            {
                "trace_id": x.get("trace_id"),
                "original_decision": x.get("original_decision"),
                "new_decision": x.get("new_decision"),
            }
            for x in changed[:5]
        ],
    }


# ---------- Tool definitions for function calling ----------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_case",
            "description": "Retrieve a specific case by ID",
            "parameters": {
                "type": "object",
                "required": ["case_id"],
                "properties": {
                    "case_id": {"type": "string", "description": "UUID of the case"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_cases",
            "description": "List recent cases in the queue for the current tenant",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20, "description": "Max cases to return"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subgraph",
            "description": "Query the entity graph around a specific entity (accounts, devices, payments, etc.)",
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string", "description": "External ID of the entity to query around"},
                    "depth": {"type": "integer", "default": 2, "description": "Graph traversal depth (1-5)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_tags",
            "description": "Get fraud tags attached to a specific entity in the graph",
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string", "description": "External ID of the entity"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_velocity",
            "description": (
                "Fetch Redis-backed event velocity (5m/1h/24h counts), distinct-device signals, "
                "and the velocity-related slice of inference_context (travel/colocation proxies, anomaly flags). "
                "Use to flag burst activity or multi-device patterns."
            ),
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity external_id (same as graph / case entity_id)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_decision_audit",
            "description": (
                "Load a stored decision audit row by trace_id: decision, score, rule_hits, tags, "
                "full inference_context (tier, drivers, SDK-related risks), recommended_action. "
                "Requires the case or evaluate response trace_id; tenant must match."
            ),
            "parameters": {
                "type": "object",
                "required": ["trace_id"],
                "properties": {
                    "trace_id": {"type": "string", "description": "UUID trace from decision evaluate / case"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subgraph_with_velocity",
            "description": (
                "Entity subgraph plus per-node velocity/inference overlay and any SDK/device fields "
                "present on graph node properties (VPN, emulator, bot, proxy, datacenter, webdriver, etc.). "
                "Prefer this over bare subgraph when analyzing rings or shared devices."
            ),
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "depth": {"type": "integer", "default": 2},
                    "max_velocity_nodes": {
                        "type": "integer",
                        "default": 10,
                        "description": "Max nodes to enrich with velocity (cap 20)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_outcome_labeled_dataset",
            "description": (
                "Export weak labels from case tags (confirmed_fraud / false_positive) and resolved disputes "
                "(outcomes fraud_confirmed, false_positive, merchant_fault, customer_fault). "
                "Use for hypothesis scoping, slice counts, or to seed ingest_labeled_rows. "
                "Dispute row wins on duplicate trace_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_limit": {"type": "integer", "default": 50, "description": "Max cases (cap 100)"},
                    "dispute_limit": {"type": "integer", "default": 50, "description": "Max disputes (cap 100)"},
                    "resolved_disputes_only": {
                        "type": "boolean",
                        "default": True,
                        "description": "If true, only status=resolved disputes with an outcome",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest_labeled_rows",
            "description": (
                "Persist analyst label drafts to case-api (tenant + analyst scoped, durable). "
                "Does not mutate case workflow labels. label must be fraud, legitimate, or unknown. "
                "Optional notes field. Max 500 drafts per analyst (oldest trimmed)."
            ),
            "parameters": {
                "type": "object",
                "required": ["rows"],
                "properties": {
                    "rows": {
                        "type": "array",
                        "description": "Up to 50 objects: {trace_id?, entity_id?, label or y_label, source?}",
                        "items": {"type": "object"},
                    },
                    "clear_existing": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete this analyst's drafts for the tenant before adding",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stored_labeled_dataset",
            "description": "List this analyst's label drafts from case-api (durable).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_batch_profile",
            "description": (
                "Summarize an uploaded tabular batch (from POST /v1/batch/ingest): columns, inferred types, row_count, sample rows. Use before deeper analysis."
            ),
            "parameters": {
                "type": "object",
                "required": ["batch_id"],
                "properties": {
                    "batch_id": {"type": "string", "description": "UUID returned by /v1/batch/ingest"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_batch_rows",
            "description": ("Read a slice of rows from an ingested CSV/JSON/Excel batch. Max 100 rows per call; use offset paging for large files."),
            "parameters": {
                "type": "object",
                "required": ["batch_id"],
                "properties": {
                    "batch_id": {"type": "string"},
                    "offset": {"type": "integer", "default": 0},
                    "limit": {"type": "integer", "default": 25, "description": "Max 100"},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional subset of columns; default all",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_batch_column",
            "description": ("Aggregate one column of an ingested batch: value_counts (top 25) or numeric_summary (min/max/mean when values parse as numbers)."),
            "parameters": {
                "type": "object",
                "required": ["batch_id", "column"],
                "properties": {
                    "batch_id": {"type": "string"},
                    "column": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["value_counts", "numeric_summary"],
                        "default": "value_counts",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Search investigation memos the analyst uploaded via POST /v1/knowledge/ingest "
                "(runbooks, policy excerpts, past writeups). Use for institutional context; "
                "still verify facts with case/graph/audit tools."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query (keywords)"},
                    "limit": {"type": "integer", "default": 5, "description": "Max hits (cap 15)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_entity_queue_snapshot",
            "description": (
                "Deterministic compare: fetches entity velocity and scans the current list_cases(limit) "
                "window for rows with the same entity_id. Use for 'how hot is this entity vs queue' "
                "without asking the model to count manually."
            ),
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "list_limit": {
                        "type": "integer",
                        "default": 80,
                        "description": "list_cases limit (10-100)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_replay_ab_comparison",
            "description": (
                "A/B replay: POST /v1/replay twice. Pass trace_ids (UUIDs, max 150) for paired evaluation on the "
                "same audits; otherwise uses limit on recent audits. Returns flip counts, missing_trace_ids, and "
                "paired disagreement metrics when trace_ids is set."
            ),
            "parameters": {
                "type": "object",
                "required": ["rules_variant_a", "rules_variant_b"],
                "properties": {
                    "rules_variant_a": {
                        "type": "array",
                        "description": "Replay rules: {id?, when:[{field,op,value}], tags?, score_delta?}",
                        "items": {"type": "object"},
                    },
                    "rules_variant_b": {
                        "type": "array",
                        "description": "Second rule set; same schema as A",
                        "items": {"type": "object"},
                    },
                    "limit": {
                        "type": "integer",
                        "default": 80,
                        "description": "Recent audit rows per variant when trace_ids omitted (cap 150)",
                    },
                    "trace_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional UUIDs for paired replay (same set for both variants, max 150)",
                    },
                },
            },
        },
    },
]

TOOL_DISPATCH = {
    "search_knowledge": tool_search_knowledge,
    "compare_entity_queue_snapshot": tool_compare_entity_queue_snapshot,
    "get_batch_profile": tool_get_batch_profile,
    "query_batch_rows": tool_query_batch_rows,
    "aggregate_batch_column": tool_aggregate_batch_column,
    "get_case": tool_get_case,
    "list_cases": tool_list_cases,
    "subgraph": tool_subgraph,
    "get_entity_tags": tool_get_entity_tags,
    "get_entity_velocity": tool_get_entity_velocity,
    "get_decision_audit": tool_get_decision_audit,
    "subgraph_with_velocity": tool_subgraph_with_velocity,
    "export_outcome_labeled_dataset": tool_export_outcome_labeled_dataset,
    "ingest_labeled_rows": tool_ingest_labeled_rows,
    "get_stored_labeled_dataset": tool_get_stored_labeled_dataset,
    "run_replay_ab_comparison": tool_run_replay_ab_comparison,
}
