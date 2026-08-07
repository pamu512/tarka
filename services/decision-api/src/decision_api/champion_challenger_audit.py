"""Champion–challenger agreement + label-gated promote posture (P0-CC)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def extract_policy_routing(payload_snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload_snapshot, Mapping):
        return None
    pr = payload_snapshot.get("policy_routing")
    return pr if isinstance(pr, dict) else None


def aggregate_champion_challenger(
    audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate shadow vs primary agreement from audit rows with policy_routing.

    Each item may be ``{"payload_snapshot": {...}, "trace_id": ..., "decision": ...}``
    or a bare ``policy_routing`` dict.
    """
    rows: list[dict[str, Any]] = []
    agree = 0
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
        decisions_agree = bool(pr.get("decisions_agree"))
        if "decisions_agree" not in pr:
            decisions_agree = champ == chall
        if decisions_agree:
            agree += 1
        rows.append(
            {
                "trace_id": str(item.get("trace_id") or "")[:64] or None,
                "champion_decision": champ,
                "challenger_decision": chall,
                "decisions_agree": decisions_agree,
                "champion_rule_score": pr.get("champion_rule_score"),
                "challenger_rule_score": pr.get("challenger_rule_score"),
                "cohort_bucket_0_99": pr.get("cohort_bucket_0_99"),
            }
        )
    n = len(rows)
    rate = (agree / n) if n else None
    # McNemar-lite contingency on decision disagree pairs (b=champ allow/chall not, c=inverse)
    b = sum(
        1
        for r in rows
        if r["champion_decision"] == "allow" and r["challenger_decision"] != "allow"
    )
    c = sum(
        1
        for r in rows
        if r["challenger_decision"] == "allow" and r["champion_decision"] != "allow"
    )
    return {
        "schema_id": "tarka.champion_challenger_audit/v1",
        "rows_with_policy_routing": n,
        "decisions_agree_count": agree,
        "decision_agreement_rate": round(rate, 4) if rate is not None else None,
        "mcnemar_contingency": {
            "b_champion_allow_challenger_stricter": b,
            "c_challenger_allow_champion_stricter": c,
            "note": "Promote science uses b/c discordant pairs; not a p-value. Wire real labels before trusting lift.",
        },
        "audit_rows": rows[:50],
    }


def label_gated_promote(
    *,
    label_posture: Mapping[str, Any],
    kill_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote allowed only when real labels are healthy AND kill_criteria pass."""
    blockers: list[str] = []
    if not label_posture.get("healthy"):
        blockers.append(str(label_posture.get("status") or "insufficient_labels"))
    if label_posture.get("label_source") == "proxy_from_decision":
        blockers.append("proxy_labels_only")
    if kill_gate is not None and not kill_gate.get("promote_allowed", True):
        for b in kill_gate.get("blockers") or []:
            blockers.append(str(b))
        if not kill_gate.get("blockers"):
            blockers.append("kill_criteria_blocked")
    # Dedupe preserve order
    seen: set[str] = set()
    uniq = []
    for b in blockers:
        if b and b not in seen:
            seen.add(b)
            uniq.append(b)
    return {
        "schema_id": "tarka.label_gated_promote/v1",
        "promote_allowed": len(uniq) == 0,
        "blockers": uniq,
        "label_posture": dict(label_posture),
        "kill_gate": (
            {k: v for k, v in kill_gate.items() if k != "metrics"} if kill_gate else None
        ),
    }


def drift_promote_gate(
    drift: Mapping[str, Any] | None,
    *,
    block_elevated: bool = True,
) -> dict[str, Any]:
    """Ojuri-adjacent PSI bar using existing L1 histogram drift (not full PSI)."""
    d = drift if isinstance(drift, Mapping) else {}
    hint = str(d.get("hint") or "")
    score = d.get("drift_score")
    blockers: list[str] = []
    if block_elevated and hint == "elevated_bin_shift_review_calibration":
        blockers.append("calibration_drift_elevated")
    return {
        "schema_id": "tarka.drift_promote_gate/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "drift_score": score,
        "hint": hint or None,
        "note": (
            "L1 bin-shift vs calibration reference — not PSI. Elevated drift blocks desk promote."
        ),
    }


def mcnemar_promote_gate(
    cc_audit: Mapping[str, Any],
    *,
    min_discordant_pairs: int = 20,
) -> dict[str, Any]:
    """Ojuri-style discordant-pair bar before trusting challenger lift (no p-value yet)."""
    cont = cc_audit.get("mcnemar_contingency")
    if not isinstance(cont, Mapping):
        cont = {}
    b = int(cont.get("b_champion_allow_challenger_stricter") or 0)
    c = int(cont.get("c_challenger_allow_champion_stricter") or 0)
    discordant = b + c
    rows = int(cc_audit.get("rows_with_policy_routing") or 0)
    blockers: list[str] = []
    if rows < 1:
        blockers.append("no_champion_challenger_rows")
    if discordant < int(min_discordant_pairs):
        blockers.append(f"discordant_pairs<{min_discordant_pairs}")
    return {
        "schema_id": "tarka.mcnemar_promote_gate/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "discordant_pairs": discordant,
        "min_discordant_pairs": int(min_discordant_pairs),
        "b_champion_allow_challenger_stricter": b,
        "c_challenger_allow_champion_stricter": c,
        "note": (
            "Contingency only — not a McNemar p-value. Combine with label_gated_promote "
            "before promoting challenger packs."
        ),
    }
