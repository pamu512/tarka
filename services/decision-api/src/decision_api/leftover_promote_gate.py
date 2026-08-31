from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import httpx

from decision_api.config import settings

MINTING = frozenset({"deny", "review"})


def _case_api_base() -> str:
    return (settings.case_api_url or "").strip().rstrip("/")


def _case_api_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    tok = (settings.case_internal_token or "").strip()
    if tok:
        headers["X-Internal-Token"] = tok
    return headers


def mapped_cc_decision_rows(audits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Champion/challenger extract matching aggregate_champion_challenger, uncapped."""
    from decision_api.champion_challenger_audit import extract_policy_routing

    rows: list[dict[str, Any]] = []
    for item in audits:
        if not isinstance(item, Mapping):
            continue
        pr = item.get("policy_routing") if "champion_decision" in item else None
        if pr is None:
            pr = extract_policy_routing(item.get("payload_snapshot"))  # type: ignore[arg-type]
        if not isinstance(pr, dict):
            continue
        champ = str(pr.get("champion_decision") or "").strip().lower()
        chall = str(pr.get("challenger_decision") or "").strip().lower()
        if not champ or not chall:
            continue
        rows.append(
            {
                "trace_id": str(item.get("trace_id") or ""),
                "entity_id": str(item.get("entity_id") or ""),
                "champion_decision": champ,
                "challenger_decision": chall,
            }
        )
    return rows


async def fetch_leftover_list(tenant_id: str) -> list[dict[str, Any]] | None:
    base = _case_api_base()
    tid = (tenant_id or "").strip()
    if not base or not tid:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/v1/leftovers",
                params={"tenant_id": tid},
                headers=_case_api_headers(),
            )
        if r.status_code >= 400:
            return None
        payload = r.json()
        rows = payload.get("leftovers")
        if not isinstance(rows, list):
            return None
        if payload.get("truncated") is True:
            return None
        return rows
    except Exception:
        return None


async def fetch_promote_ack(tenant_id: str, draft_id: str) -> dict[str, Any] | None:
    base = _case_api_base()
    tid = (tenant_id or "").strip()
    did = (draft_id or "").strip()
    if not base or not tid or not did:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/v1/leftovers/promote-ack",
                params={"tenant_id": tid, "draft_id": did},
                headers=_case_api_headers(),
            )
        if r.status_code < 200 or r.status_code >= 300:
            return None
        ack = r.json().get("ack")
        return ack if isinstance(ack, dict) else None
    except Exception:
        return None


def leftover_caps_for_tenant(tenant_id: str) -> tuple[int, float, int]:
    """Provision caps when version >= 1; else env defaults (pre-review)."""
    tid = (tenant_id or "").strip()
    if tid:
        from decision_api.shadow_auto_promote import load_provision

        prov = load_provision(tid)
        if int(prov.get("version") or 0) >= 1:
            return (
                int(prov["leftover_add_cap"]),
                float(prov["leftover_fp_rate_cap"]),
                int(prov["min_labeled_extras"]),
            )
    try:
        add_cap = int(os.environ.get("LEFTOVER_PROMOTE_ADD_CAP", "10"))
    except (TypeError, ValueError):
        add_cap = 10
    try:
        fp_rate_cap = float(os.environ.get("LEFTOVER_PROMOTE_FP_RATE_CAP", "0.4"))
    except (TypeError, ValueError):
        fp_rate_cap = 0.4
    try:
        min_labeled_extras = int(os.environ.get("LEFTOVER_PROMOTE_MIN_LABELED_EXTRAS", "5"))
    except (TypeError, ValueError):
        min_labeled_extras = 5
    return add_cap, fp_rate_cap, min_labeled_extras


def extra_review_or_deny_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        champ = str(row.get("champion_decision") or "").strip().lower()
        chall = str(row.get("challenger_decision") or "").strip().lower()
        if champ and chall and champ not in MINTING and chall in MINTING:
            out.append(dict(row))
    return out


def extra_leftover_mint_count(extras: Sequence[Mapping[str, Any]], *, mint_on: bool) -> int:
    return len(extras) if mint_on else 0


def leftover_helpfulness(
    extras: Sequence[Mapping[str, Any]],
    *,
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
    min_labeled_extras: int = 5,
    fp_rate_cap: float = 0.4,
) -> dict[str, Any]:
    extra_tp = 0
    extra_fp = 0
    labeled = 0
    for row in extras:
        tid = str(row.get("trace_id") or "").strip()
        eid = str(row.get("entity_id") or "").strip()
        lab = by_trace.get(tid) if tid else None
        if lab is None and eid:
            lab = by_entity.get(eid)
        if lab not in {"0", "1"}:
            continue
        labeled += 1
        if lab == "1":
            extra_tp += 1
        else:
            extra_fp += 1
    fp_rate = (extra_fp / labeled) if labeled else None
    underpowered = labeled < min_labeled_extras
    blockers: list[str] = []
    if not underpowered and fp_rate is not None and fp_rate > fp_rate_cap:
        blockers.append("leftover_extras_fp_over_cap")
    if not underpowered and extra_tp == 0 and extra_fp >= min_labeled_extras:
        blockers.append("leftover_extras_no_lift")
    return {
        "labeled_extras": labeled,
        "extra_tp": extra_tp,
        "extra_fp": extra_fp,
        "fp_rate": round(fp_rate, 4) if fp_rate is not None else None,
        "fp_rate_cap": fp_rate_cap,
        "min_labeled_extras": min_labeled_extras,
        "underpowered": underpowered,
        "blockers": blockers,
    }


def ack_is_valid(ack: Mapping[str, Any] | None, claimers: Sequence[str]) -> bool:
    if not ack:
        return False
    who = str(ack.get("acked_by") or "").strip()
    return bool(who) and who in {str(c).strip() for c in claimers if str(c).strip()}


def leftover_promote_gate(
    *,
    leftovers: list[dict[str, Any]] | None,
    extras: Sequence[Mapping[str, Any]],
    mint_on: bool,
    add_cap: int,
    helpfulness: Mapping[str, Any],
    ack: Mapping[str, Any] | None,
    draft_id: str | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    leftover_count = 0
    sla_n = 0
    claimers: list[str] = []
    if leftovers is None:
        blockers.append("leftover_queue_unavailable")
    else:
        leftover_count = len(leftovers)
        for row in leftovers:
            if row.get("sla_breached"):
                sla_n += 1
            who = str(row.get("claimed_by") or "").strip()
            if who and who not in claimers:
                claimers.append(who)
        if sla_n:
            blockers.append("leftover_sla_breached")
    mint_n = extra_leftover_mint_count(extras, mint_on=mint_on)
    if mint_n > add_cap:
        blockers.append("leftover_add_over_cap")
    ack_required = bool(claimers)
    if ack_required and not ack_is_valid(ack, claimers):
        blockers.append("leftover_claimer_ack_required")
    for b in helpfulness.get("blockers") or []:
        if b not in blockers:
            blockers.append(str(b))
    hint = "queue_empty"
    if leftovers is None:
        hint = "leftover_queue_unavailable"
    elif helpfulness.get("underpowered") and extras:
        hint = "helpfulness_underpowered"
    elif not extras:
        hint = "no_observe_pairs"
    elif not mint_on:
        hint = "mint_off_extras_are_display_only"
    return {
        "schema_id": "tarka.leftover_promote_gate/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "extra_review_or_deny": len(extras),
        "extra_leftover_mint": mint_n,
        "leftover_mint_on": bool(mint_on),
        "cap": add_cap,
        "sla_breached_count": sla_n,
        "leftover_count": leftover_count,
        "claimers": claimers,
        "ack_required": ack_required,
        "ack": dict(ack) if ack else None,
        "helpfulness": dict(helpfulness),
        "hint": hint,
        "draft_id": draft_id,
    }


def _desk_promote_from_parts(
    live_promote: Mapping[str, Any],
    mcnemar: Mapping[str, Any],
    drift_gate: Mapping[str, Any],
    leftover_g: Mapping[str, Any],
) -> dict[str, Any]:
    combined: list[str] = []
    seen: set[str] = set()
    for src in (live_promote, mcnemar, drift_gate, leftover_g):
        for b in src.get("blockers") or []:
            if b and b not in seen:
                seen.add(str(b))
                combined.append(str(b))
    return {
        "schema_id": "tarka.desk_promote_gate/v1",
        "promote_allowed": len(combined) == 0,
        "blockers": combined,
        "requires": [
            "label_gated_promote",
            "mcnemar_promote_gate",
            "drift_promote_gate",
            "leftover_promote_gate",
        ],
    }


async def compute_desk_and_leftover_gates(
    tenant_id: str,
    draft_id: str | None = None,
    *,
    session: Any = None,
) -> dict[str, Any]:
    """Leftover floor + desk science (labels/McNemar/drift) for one tenant/draft."""
    from decision_api.champion_challenger_audit import (
        aggregate_champion_challenger,
        drift_promote_gate,
        label_gated_promote,
        labeled_champion_challenger_f1,
        mcnemar_promote_gate,
    )
    from decision_api.config import settings
    from decision_api.y_label_store import load_y_labels

    tid = (tenant_id or "").strip()
    did = (draft_id or "").strip() or None
    label_posture: dict[str, Any] = {
        "healthy": False,
        "status": "no_tenant",
        "label_coverage": 0.0,
        "hint": "Pass tenant_id to scan real-label coverage before promote.",
    }
    cc_audit: dict[str, Any] = aggregate_champion_challenger([])
    labeled_f1: dict[str, Any] = labeled_champion_challenger_f1([])
    cc_rows: list[dict[str, Any]] = []
    y_by_trace: dict[str, str] = {}
    y_by_entity: dict[str, str] = {}
    slip: dict[str, Any] = {"window": "underpowered", "fp_cap": 0.4, "rules": []}
    slip_rows: list[dict[str, Any]] = []
    scanned = False
    if tid and session is not None:
        try:
            from sqlalchemy import select

            from decision_api.label_join import label_coverage_posture
            from decision_api.models import AuditRecord
            from decision_api.reliability_export import (
                audit_row_to_export_dict,
                reliability_bins,
            )

            stmt = (
                select(AuditRecord)
                .where(AuditRecord.tenant_id == tid)
                .order_by(AuditRecord.created_at.desc())
                .limit(500)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            export_rows = [
                audit_row_to_export_dict(
                    {
                        "trace_id": rec.trace_id,
                        "tenant_id": rec.tenant_id,
                        "entity_id": rec.entity_id,
                        "event_type": rec.event_type,
                        "decision": rec.decision,
                        "score": rec.score,
                        "payload_snapshot": rec.payload_snapshot,
                        "created_at": rec.created_at,
                    }
                )
                for rec in records
            ]
            bins = reliability_bins(export_rows, n_bins=10, use_proxy_labels=True)
            label_posture = label_coverage_posture(
                label_coverage=float(bins.get("label_coverage") or 0.0),
                proxy_only=bins.get("label_source") == "proxy_from_decision",
            )
            label_posture["label_source"] = bins.get("label_source")
            label_posture["rows_scanned"] = len(export_rows)
            cc_rows = [
                {
                    "trace_id": str(rec.trace_id),
                    "entity_id": str(rec.entity_id or ""),
                    "payload_snapshot": rec.payload_snapshot
                    if isinstance(rec.payload_snapshot, dict)
                    else {},
                }
                for rec in records
            ]
            slip_rows = [
                {
                    "trace_id": str(rec.trace_id),
                    "entity_id": str(rec.entity_id or ""),
                    "event_type": rec.event_type,
                    "decision": rec.decision,
                    "rule_hits": list(rec.rule_hits or []),
                    "payload_snapshot": rec.payload_snapshot
                    if isinstance(rec.payload_snapshot, dict)
                    else {},
                }
                for rec in records
            ]
            cc_audit = aggregate_champion_challenger(cc_rows)
            ystore = load_y_labels(tid)
            y_by_trace = dict(ystore.get("by_trace") or {})
            y_by_entity = dict(ystore.get("by_entity") or {})
            labeled_f1 = labeled_champion_challenger_f1(
                cc_rows,
                by_trace=y_by_trace,
                by_entity=y_by_entity,
            )
            scanned = True
        except Exception:
            label_posture = {
                "healthy": False,
                "status": "label_coverage_unavailable",
                "label_coverage": 0.0,
                "hint": "audit scan failed",
            }

    live_promote = label_gated_promote(label_posture=label_posture, kill_gate=None)
    mcnemar = mcnemar_promote_gate(cc_audit)
    drift_row: dict[str, Any] = {"hint": "no_tenant"}
    if tid:
        from decision_api.calibration_api import compute_drift_for_tenant

        drift_row = compute_drift_for_tenant(tid, "default")
        if not y_by_trace and not y_by_entity:
            try:
                ystore = load_y_labels(tid)
                y_by_trace = dict(ystore.get("by_trace") or {})
                y_by_entity = dict(ystore.get("by_entity") or {})
            except Exception:
                y_by_trace, y_by_entity = {}, {}
    drift_gate = drift_promote_gate(drift_row)
    extras = extra_review_or_deny_rows(mapped_cc_decision_rows(cc_rows))
    add_cap, fp_rate_cap, min_labeled_extras = leftover_caps_for_tenant(tid)
    if scanned:
        from decision_api.json_rules import get_shadow_packs
        from decision_api.live_rule_slip import live_rule_slip

        slip = live_rule_slip(
            slip_rows,
            by_trace=y_by_trace,
            by_entity=y_by_entity,
            fp_cap=fp_rate_cap,
            parked=get_shadow_packs(),
        )
    from decision_api.rule_label_metrics import rule_precision_after_labels

    labeled_rows: list[dict[str, Any]] = []
    for row in slip_rows:
        item = dict(row)
        row_tid = str(item.get("trace_id") or "").strip()
        eid = str(item.get("entity_id") or "").strip()
        lab = y_by_trace.get(row_tid) if row_tid else None
        if lab is None and eid:
            lab = y_by_entity.get(eid)
        item["y_label"] = lab if lab in {"0", "1"} else ""
        labeled_rows.append(item)
    precision = rule_precision_after_labels(labeled_rows)
    leftovers = await fetch_leftover_list(tid)
    leftover_g = leftover_promote_gate(
        leftovers=leftovers,
        extras=extras,
        mint_on=bool(settings.case_create_on_deny_review),
        add_cap=add_cap,
        helpfulness=leftover_helpfulness(
            extras,
            by_trace=y_by_trace,
            by_entity=y_by_entity,
            min_labeled_extras=min_labeled_extras,
            fp_rate_cap=fp_rate_cap,
        ),
        ack=await fetch_promote_ack(tid, did or ""),
        draft_id=did,
    )
    desk_promote = _desk_promote_from_parts(
        live_promote, mcnemar, drift_gate, leftover_g
    )
    return {
        "leftover_promote_gate": leftover_g,
        "desk_promote_gate": desk_promote,
        "label_gated_promote": live_promote,
        "mcnemar_promote_gate": mcnemar,
        "drift_promote_gate": drift_gate,
        "champion_challenger": cc_audit,
        "labeled_champion_challenger_f1": labeled_f1,
        "label_posture": label_posture,
        "live_rule_slip": slip,
        "rule_precision_after_labels": precision,
    }
