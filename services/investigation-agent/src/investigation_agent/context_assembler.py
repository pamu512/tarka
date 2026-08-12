"""Deterministic case/entity/trace context snapshot (no LLM)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

SCHEMA_ID = "tarka.context_snapshot/v1"
_EXCERPT_CAP = 480


def _stable_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _excerpt(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj[:_EXCERPT_CAP]
    try:
        return json.dumps(obj, sort_keys=True, default=str)[:_EXCERPT_CAP]
    except TypeError:
        return str(obj)[:_EXCERPT_CAP]


def _artifact(
    *,
    source: str,
    evidence_id: str,
    payload: Any,
    sensitivity: str = "analyst_view",
    json_pointer: str | None = None,
    freshness: str = "present",
    observed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "evidence_id": evidence_id,
        "json_pointer": json_pointer,
        "content_hash": _stable_hash(payload) if payload is not None else "",
        "sensitivity": sensitivity,
        "observed_at": observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "freshness": freshness,
        "excerpt": _excerpt(payload),
    }


def assemble_context_snapshot(
    *,
    tenant_id: str,
    case_id: str | None = None,
    entity_id: str | None = None,
    trace_id: str | None = None,
    case_payload: dict[str, Any] | None = None,
    decision_audit: dict[str, Any] | list[Any] | None = None,
    entity_velocity: dict[str, Any] | None = None,
    graph_neighborhood: dict[str, Any] | None = None,
    okf_hits: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build an immutable ``tarka.context_snapshot/v1`` from caller-supplied artifacts.

    Missing sources are recorded with ``freshness=missing`` (never invented).
    Optional ``tool_results`` (chat tool_calls) are scanned for known tool names.
    """
    tid = (tenant_id or "").strip()
    as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    artifacts: list[dict[str, Any]] = []
    freshness: dict[str, str] = {}

    case_obj = case_payload
    decision_obj = decision_audit
    velocity_obj = entity_velocity
    graph_obj = graph_neighborhood
    okf_list = list(okf_hits or [])

    for call in tool_results or []:
        if not isinstance(call, dict):
            continue
        name = str(call.get("tool") or call.get("name") or "").strip()
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("error"):
            continue
        if name in {"get_case", "list_cases"} and case_obj is None:
            case_obj = result.get("case") if isinstance(result.get("case"), dict) else result
        elif name in {"get_decision_audit", "decision_audit"} and decision_obj is None:
            decision_obj = result.get("audit") if "audit" in result else result
        elif name in {"get_entity_velocity", "entity_velocity"} and velocity_obj is None:
            velocity_obj = result
        elif name in {"query_graph", "get_graph_neighborhood", "graph_neighborhood"} and graph_obj is None:
            graph_obj = result
        elif name == "search_knowledge":
            hits = result.get("hits")
            if isinstance(hits, list):
                for h in hits:
                    if isinstance(h, dict) and h.get("knowledge_kind") == "okf":
                        okf_list.append(h)

    cid = (case_id or "").strip() or (
        str(case_obj.get("id") or case_obj.get("case_id") or "").strip()
        if isinstance(case_obj, dict)
        else ""
    )
    eid = (entity_id or "").strip()
    trid = (trace_id or "").strip()

    if case_obj is not None:
        freshness["case"] = "present"
        artifacts.append(
            _artifact(
                source="case",
                evidence_id=f"case:{cid or _stable_hash(case_obj)[:16]}",
                payload=case_obj,
                observed_at=as_of,
            )
        )
    else:
        freshness["case"] = "missing"

    if decision_obj is not None:
        freshness["decision_audit"] = "present"
        artifacts.append(
            _artifact(
                source="decision_audit",
                evidence_id=f"decision_audit:{_stable_hash(decision_obj)[:16]}",
                payload=decision_obj,
                observed_at=as_of,
            )
        )
    else:
        freshness["decision_audit"] = "missing"

    if velocity_obj is not None:
        freshness["entity_velocity"] = "present"
        artifacts.append(
            _artifact(
                source="entity_velocity",
                evidence_id=f"entity_velocity:{_stable_hash(velocity_obj)[:16]}",
                payload=velocity_obj,
                observed_at=as_of,
            )
        )
    else:
        freshness["entity_velocity"] = "missing"

    if graph_obj is not None:
        freshness["graph"] = "present"
        artifacts.append(
            _artifact(
                source="graph",
                evidence_id=f"graph:{_stable_hash(graph_obj)[:16]}",
                payload=graph_obj,
                observed_at=as_of,
            )
        )
    else:
        freshness["graph"] = "missing"

    if okf_list:
        freshness["okf"] = "present"
        for i, hit in enumerate(okf_list[:40]):
            concept_id = str(hit.get("concept_id") or hit.get("id") or i)
            artifacts.append(
                _artifact(
                    source="okf",
                    evidence_id=f"okf:{concept_id}",
                    payload=hit,
                    observed_at=as_of,
                )
            )
    else:
        freshness["okf"] = "missing"

    snapshot = {
        "schema_id": SCHEMA_ID,
        "as_of": as_of,
        "tenant_id": tid,
        "case_id": cid or None,
        "entity_id": eid or None,
        "trace_id": trid or None,
        "keys_present": sorted(k for k, v in freshness.items() if v == "present"),
        "freshness": freshness,
        "artifacts": artifacts,
    }
    snapshot["snapshot_sha256"] = _stable_hash(
        {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    )
    return snapshot


def render_deterministic_case_brief(
    snapshot: dict[str, Any],
    *,
    case_payload: dict[str, Any] | None = None,
) -> str:
    """Markdown brief from a context snapshot (no LLM)."""
    case = case_payload if isinstance(case_payload, dict) else {}
    lines = [
        "# Case brief (deterministic)",
        "",
        f"- schema: `{snapshot.get('schema_id')}`",
        f"- as_of: `{snapshot.get('as_of')}`",
        f"- tenant_id: `{snapshot.get('tenant_id')}`",
        f"- case_id: `{snapshot.get('case_id') or '—'}`",
        f"- entity_id: `{snapshot.get('entity_id') or '—'}`",
        f"- trace_id: `{snapshot.get('trace_id') or case.get('trace_id') or '—'}`",
        f"- keys_present: {', '.join(snapshot.get('keys_present') or []) or '—'}",
    ]
    status = str(case.get("status") or "").strip()
    priority = str(case.get("priority") or "").strip()
    title = str(case.get("title") or "").strip()
    if title:
        lines.append(f"- title: {title[:200]}")
    if status:
        lines.append(f"- status: `{status}`")
    if priority:
        lines.append(f"- priority: `{priority}`")
    labels = case.get("labels")
    if isinstance(labels, list) and labels:
        lab = ", ".join(str(x) for x in labels[:20] if str(x).strip())
        if lab:
            lines.append(f"- labels: {lab}")
    lines.append("")
    lines.append("## Freshness")
    for src, state in sorted((snapshot.get("freshness") or {}).items()):
        lines.append(f"- **{src}**: {state}")
    lines.append("")
    lines.append("## Artifacts")
    arts = snapshot.get("artifacts") or []
    if not arts:
        lines.append("- (none)")
    else:
        for a in arts[:30]:
            if not isinstance(a, dict):
                continue
            lines.append(
                f"- `{a.get('evidence_id')}` ({a.get('source')}) hash=`{(a.get('content_hash') or '')[:12]}…`"
            )
            ex = (a.get("excerpt") or "").strip()
            if ex:
                lines.append(f"  - excerpt: {ex[:200]}")
    lines.append("")
    lines.append(f"snapshot_sha256: `{snapshot.get('snapshot_sha256')}`")
    return "\n".join(lines)


def claims_with_evidence_ids(
    claims: list[dict[str, Any]] | None,
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Bind tool claims to snapshot evidence_ids that the claim text actually grounds.

    Never slap every artifact onto every claim. Prefer explicit claim.evidence_ids.
    """
    artifacts = [
        a
        for a in (snapshot or {}).get("artifacts") or []
        if isinstance(a, dict) and a.get("evidence_id")
    ]
    out: list[dict[str, Any]] = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        row = dict(c)
        existing = row.get("evidence_ids")
        if isinstance(existing, list) and any(str(x).strip() for x in existing):
            row["evidence_ids"] = [str(x).strip() for x in existing if str(x).strip()][:20]
            out.append(row)
            continue
        if str(row.get("source") or "") != "tool":
            out.append(row)
            continue
        text = str(row.get("text") or "").lower()
        matched: list[str] = []
        for a in artifacts:
            eid = str(a.get("evidence_id") or "").strip()
            if not eid:
                continue
            src = str(a.get("source") or "").strip().lower()
            excerpt = str(a.get("excerpt") or "").lower()
            token_ok = eid.lower() in text or (src and src in text)
            excerpt_ok = False
            if excerpt:
                frag = excerpt[:48].strip()
                if len(frag) >= 8 and frag in text:
                    excerpt_ok = True
            tail = eid.split(":", 1)[-1] if ":" in eid else eid
            tail_ok = len(tail) >= 4 and tail.lower() in text
            if token_ok or excerpt_ok or tail_ok:
                matched.append(eid)
        if matched:
            row["evidence_ids"] = matched[:20]
        out.append(row)
    return out
