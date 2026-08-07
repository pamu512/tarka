"""Champion–challenger agreement + label-gated promote posture (P0-CC / Ojuri)."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def population_stability_index(
    ref_hist: Mapping[str, Any],
    cur_hist: Mapping[str, Any],
    *,
    epsilon: float = 1e-6,
) -> float | None:
    """Classic PSI on count histograms (Ojuri-style drift bar)."""
    keys = sorted(set(ref_hist.keys()) | set(cur_hist.keys()))
    if not keys:
        return None
    total_r = sum(float(ref_hist.get(k, 0) or 0) for k in keys)
    total_c = sum(float(cur_hist.get(k, 0) or 0) for k in keys)
    if total_r <= 0 or total_c <= 0:
        return None
    psi = 0.0
    for k in keys:
        pr = max(float(ref_hist.get(k, 0) or 0) / total_r, epsilon)
        pc = max(float(cur_hist.get(k, 0) or 0) / total_c, epsilon)
        psi += (pc - pr) * math.log(pc / pr)
    return round(psi, 6)


def promote_lifecycle_stage(
    *,
    label_ok: bool,
    mcnemar_ok: bool,
    drift_ok: bool,
    desk_ok: bool,
) -> dict[str, Any]:
    """Ojuri-style CANDIDATE → SHADOW → ACTIVE (desk promote science)."""
    if desk_ok and label_ok and mcnemar_ok and drift_ok:
        stage = "ACTIVE"
    elif label_ok:
        stage = "SHADOW"
    else:
        stage = "CANDIDATE"
    return {
        "schema_id": "tarka.promote_lifecycle/v1",
        "stage": stage,
        "stages": ["CANDIDATE", "SHADOW", "ACTIVE"],
        "gates": {
            "labels": label_ok,
            "mcnemar": mcnemar_ok,
            "drift_psi": drift_ok,
            "desk_promote": desk_ok,
        },
        "note": (
            "CANDIDATE=insufficient labels; SHADOW=labels ok, waiting McNemar/PSI; "
            "ACTIVE=desk_promote_allowed. Not Ojuri's full MLA pipeline."
        ),
    }


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
            "note": (
                "Discordant pairs for McNemar; p-value computed in mcnemar_promote_gate. "
                "Wire real labels before trusting lift."
            ),
        },
        "audit_rows": rows[:50],
    }


def mcnemar_pvalue(b: int, c: int) -> dict[str, Any]:
    """Two-sided McNemar under H0: P(b)=P(c)=0.5.

    Exact binomial for n<25; Edwards continuity-corrected χ² (df=1) otherwise.
    Also returns mid-p (exact path subtracts half the mass at the observed min).
    """
    bb = max(0, int(b))
    cc = max(0, int(c))
    n = bb + cc
    if n == 0:
        return {
            "p_value": None,
            "mid_p": None,
            "method": "empty",
            "n_discordant": 0,
            "chi2": None,
        }
    if n < 25:
        k = min(bb, cc)
        # Python int unlimited — sum C(n,i) / 2^n
        tail = sum(math.comb(n, i) for i in range(k + 1))
        denom = 1 << n
        p_one = tail / denom
        p = 1.0 if (k * 2 == n) else min(1.0, 2.0 * p_one)
        p_obs = math.comb(n, k) / denom
        mid = 1.0 if (k * 2 == n) else min(1.0, max(0.0, p - p_obs))
        return {
            "p_value": round(p, 6),
            "mid_p": round(mid, 6),
            "method": "exact_binomial",
            "n_discordant": n,
            "chi2": None,
        }
    # Edwards continuity correction: (|b-c|-1)^2 / (b+c)
    chi2 = ((abs(bb - cc) - 1) ** 2) / float(n)
    # χ²(1) survival = erfc(sqrt(x/2))
    p = float(math.erfc(math.sqrt(chi2 / 2.0)))
    return {
        "p_value": round(min(1.0, max(0.0, p)), 6),
        "mid_p": round(min(1.0, max(0.0, p)), 6),
        "method": "chi2_continuity",
        "n_discordant": n,
        "chi2": round(chi2, 6),
    }


def _binary_f1(y_true: Sequence[int], y_pred: Sequence[int]) -> float | None:
    if not y_true or len(y_true) != len(y_pred):
        return None
    tp = fp = fn = 0
    for yt, yp in zip(y_true, y_pred):
        if yp == 1 and yt == 1:
            tp += 1
        elif yp == 1 and yt == 0:
            fp += 1
        elif yp == 0 and yt == 1:
            fn += 1
    if tp + fp + fn == 0:
        return None  # all TN — F1 undefined for fraud class
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    if prec + rec <= 0:
        return 0.0
    return round(2.0 * prec * rec / (prec + rec), 4)


def labeled_champion_challenger_f1(
    audits: Sequence[Mapping[str, Any]],
    *,
    by_trace: Mapping[str, str] | None = None,
    by_entity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """F1 on labeled rows: predicted positive = decision != allow (fraud class=1)."""
    tmap = by_trace or {}
    emap = by_entity or {}
    y_true: list[int] = []
    y_champ: list[int] = []
    y_chall: list[int] = []
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
        tid = str(item.get("trace_id") or "").strip()
        eid = str(item.get("entity_id") or "").strip()
        lab = tmap.get(tid) if tid else None
        if lab is None and eid:
            lab = emap.get(eid)
        if lab not in {"0", "1"}:
            continue
        y_true.append(1 if lab == "1" else 0)
        y_champ.append(0 if champ == "allow" else 1)
        y_chall.append(0 if chall == "allow" else 1)
    n = len(y_true)
    return {
        "schema_id": "tarka.labeled_champion_challenger_f1/v1",
        "labeled_rows": n,
        "champion_f1": _binary_f1(y_true, y_champ) if n else None,
        "challenger_f1": _binary_f1(y_true, y_chall) if n else None,
        "note": (
            "Requires durable y_label join (trace/entity). Proxy labels excluded. "
            "Not Ojuri's full MLA training loop."
        ),
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
    max_psi: float = 0.25,
) -> dict[str, Any]:
    """Ojuri-style drift bar: elevated L1 bin-shift and/or PSI above max_psi."""
    d = drift if isinstance(drift, Mapping) else {}
    hint = str(d.get("hint") or "")
    score = d.get("drift_score")
    psi = d.get("psi")
    blockers: list[str] = []
    if block_elevated and hint == "elevated_bin_shift_review_calibration":
        blockers.append("calibration_drift_elevated")
    try:
        psi_f = float(psi) if psi is not None else None
    except (TypeError, ValueError):
        psi_f = None
    if psi_f is not None and psi_f > float(max_psi):
        blockers.append(f"psi>{max_psi}")
    return {
        "schema_id": "tarka.drift_promote_gate/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "drift_score": score,
        "psi": psi_f,
        "max_psi": float(max_psi),
        "hint": hint or None,
        "note": (
            "L1 bin-shift + population_stability_index on calibration histograms. "
            "Elevated drift or PSI blocks desk promote."
        ),
    }


def mcnemar_promote_gate(
    cc_audit: Mapping[str, Any],
    *,
    min_discordant_pairs: int = 20,
    alpha: float = 0.05,
    require_significance: bool = True,
) -> dict[str, Any]:
    """Ojuri-style McNemar bar: discordant volume + two-sided p-value / mid-p."""
    cont = cc_audit.get("mcnemar_contingency")
    if not isinstance(cont, Mapping):
        cont = {}
    b = int(cont.get("b_champion_allow_challenger_stricter") or 0)
    c = int(cont.get("c_challenger_allow_champion_stricter") or 0)
    discordant = b + c
    rows = int(cc_audit.get("rows_with_policy_routing") or 0)
    stats = mcnemar_pvalue(b, c)
    # Prefer mid-p when available (exact path); else p_value
    p_gate = stats.get("mid_p")
    if p_gate is None:
        p_gate = stats.get("p_value")
    blockers: list[str] = []
    if rows < 1:
        blockers.append("no_champion_challenger_rows")
    if discordant < int(min_discordant_pairs):
        blockers.append(f"discordant_pairs<{min_discordant_pairs}")
    if require_significance:
        if p_gate is None:
            blockers.append("mcnemar_p_unavailable")
        elif float(p_gate) >= float(alpha):
            blockers.append(f"mcnemar_mid_p>={alpha}")
    return {
        "schema_id": "tarka.mcnemar_promote_gate/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "discordant_pairs": discordant,
        "min_discordant_pairs": int(min_discordant_pairs),
        "b_champion_allow_challenger_stricter": b,
        "c_challenger_allow_champion_stricter": c,
        "p_value": stats.get("p_value"),
        "mid_p": stats.get("mid_p"),
        "method": stats.get("method"),
        "chi2": stats.get("chi2"),
        "alpha": float(alpha),
        "require_significance": bool(require_significance),
        "note": (
            "Exact binomial (n<25) or Edwards χ² continuity; gate uses mid_p < alpha "
            "plus discordant volume. Combine with label_gated_promote."
        ),
    }
