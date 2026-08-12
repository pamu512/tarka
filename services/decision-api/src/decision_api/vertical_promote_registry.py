"""Per-vertical fixture holdout promote science (no LIVE labels required).

Honesty: ``promote_live_claim_allowed`` stays false; fixture-proven promote is
``promote_fixture_claim_allowed`` when F1 + McNemar gates pass on labeled JSONL.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from decision_api.champion_challenger_audit import mcnemar_promote_gate
from decision_api.vertical_packs import evaluate_kill_criteria, get_vertical_pack

log = logging.getLogger("decision-api.vertical_promote_registry")

_PRIORITY_VERTICALS = ("marketplace", "food_delivery", "e_hailing")
_DEFAULT_SCORE_THRESHOLD = 30.0

# Bundled holdouts live next to tests; override via env path if needed.
_HOLDOUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "labels"
    / "vertical_holdouts"
)


def holdout_dir() -> Path:
    return _HOLDOUT_DIR


def holdout_path(vertical: str) -> Path:
    return holdout_dir() / f"{vertical}.jsonl"


def load_holdout_rows(vertical: str) -> list[dict[str, Any]]:
    path = holdout_path(vertical)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            log.warning("holdout_bad_json vertical=%s line=%s err=%s", vertical, i, e)
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _pack_score(
    features: dict[str, Any], rules: list[dict[str, Any]]
) -> tuple[float, list[str]]:
    from decision_api.json_rules import _match_condition

    hits: list[str] = []
    delta = 0.0
    for rule in rules:
        conditions = rule.get("when") or []
        if conditions and all(_match_condition(features, c) for c in conditions):
            hits.append(str(rule.get("id") or "rule"))
            delta += float(rule.get("score_delta") or 0)
    return max(0.0, min(100.0, 10.0 + delta)), hits


def _binary_metrics(y_true: list[int], y_pred: list[int]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for yt, yp in zip(y_true, y_pred, strict=True):
        if yt == 1 and yp == 1:
            tp += 1
        elif yt == 0 and yp == 1:
            fp += 1
        elif yt == 0 and yp == 0:
            tn += 1
        else:
            fn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(prec, 6),
        "recall": round(rec, 6),
        "false_positive_rate": round(fpr, 6),
        "f1_score": round(f1, 6),
        "events_evaluated": len(y_true),
    }


def evaluate_holdout_for_pack(
    vertical: str,
    *,
    score_threshold: float = _DEFAULT_SCORE_THRESHOLD,
    pack_id: str | None = None,
) -> dict[str, Any]:
    """Score pack rules on labeled holdout; return metrics + McNemar vs always-allow."""
    pid = pack_id or vertical
    pack = get_vertical_pack(pid)
    rows = load_holdout_rows(vertical)
    if pack is None:
        return {
            "vertical": vertical,
            "pack_id": pid,
            "error": "pack_not_found",
            "rows": 0,
        }
    if not rows:
        return {
            "vertical": vertical,
            "pack_id": pid,
            "error": "holdout_missing",
            "rows": 0,
            "holdout_path": str(holdout_path(vertical)),
        }

    rules = list(pack.get("rules") or [])
    y_true: list[int] = []
    y_pack: list[int] = []
    y_champ: list[int] = []  # always-allow champion → never positive
    b = c = 0  # McNemar discordant: champ allow / chall stricter vs reverse
    for row in rows:
        feats = dict(row.get("features") or {})
        try:
            y = int(row.get("y"))
        except (TypeError, ValueError):
            continue
        if y not in (0, 1):
            continue
        score, _hits = _pack_score(feats, rules)
        pred = 1 if score >= score_threshold else 0
        champ = 0  # always allow
        y_true.append(y)
        y_pack.append(pred)
        y_champ.append(champ)
        if champ == 0 and pred == 1:
            b += 1
        elif champ == 1 and pred == 0:
            c += 1

    metrics = _binary_metrics(y_true, y_pack)
    kill = evaluate_kill_criteria(
        metrics,
        pack.get("kill_criteria"),
        events_evaluated=int(metrics.get("events_evaluated") or 0),
    )
    # Fixture McNemar: require volume; significance optional when c==0 (one-sided ladder)
    cc_audit = {
        "rows_with_policy_routing": len(y_true),
        "mcnemar_contingency": {
            "b_champion_allow_challenger_stricter": b,
            "c_challenger_allow_champion_stricter": c,
        },
    }
    mcn = mcnemar_promote_gate(
        cc_audit,
        min_discordant_pairs=20,
        alpha=0.05,
        require_significance=(c > 0),
    )
    blockers = list(kill.get("blockers") or [])
    # Explicit F1 bar for fixture science (pack kill_criteria alone can be very loose)
    criteria = pack.get("kill_criteria") or {}
    min_f1 = float(criteria.get("min_f1_fixture") or 0.35)
    if float(metrics.get("f1_score") or 0.0) < min_f1:
        blockers.append(f"f1_below_fixture_min:{min_f1}")
    if not mcn.get("promote_allowed"):
        for x in mcn.get("blockers") or []:
            blockers.append(f"mcnemar:{x}")
    # Realism accounting — offline path: near-miss coverage is a hard CI gate
    near_miss = sum(
        1
        for r in rows
        if str(r.get("difficulty") or "").lower()
        in ("near_miss", "hard_negative", "adversarial")
    )
    near_miss_ratio = round(near_miss / len(rows), 4) if rows else 0.0
    realism = {
        "near_miss_or_hard_negative_rows": near_miss,
        "near_miss_ratio": near_miss_ratio,
        "tenant_labeled": False,
        "synthetic_only": True,
        "min_near_miss_rows": 5,
        "min_near_miss_ratio": 0.05,
    }
    min_nm = max(5, int(0.05 * len(rows)))
    if near_miss < min_nm:
        blockers.append(f"holdout_near_miss_below_min:{near_miss}<{min_nm}")
        realism["warning"] = "holdout_lacks_near_miss_coverage"

    # Fixture ECE critical blocks promote (calibration as CI, not LIVE claim)
    try:
        from decision_api.vertical_calibration import fixture_ece_snapshot

        cal = fixture_ece_snapshot(vertical)
        realism["fixture_ece"] = cal.get("expected_calibration_error")
        realism["fixture_drift_flag"] = cal.get("drift_flag")
        realism["fixture_ece_bin_count"] = cal.get("bin_count")
        realism["fixture_ece_populated_bins"] = cal.get("populated_bin_count")
        # Compact bin digest for ops/CI (full posture also on /v1/ops/vertical-calibration)
        realism["fixture_reliability_bins"] = cal.get("reliability_bins") or []
        if cal.get("drift_flag") == "critical":
            blockers.append("fixture_ece_drift_critical")
        if int(cal.get("populated_bin_count") or 0) < 2:
            realism["fixture_ece_bins_warning"] = "sparse_populated_bins"
    except Exception as e:  # pragma: no cover — calibration optional fail-soft
        log.warning("promote_calibration_check_failed vertical=%s err=%s", vertical, e)

    # Honesty fields
    promote_fixture = len(blockers) == 0

    return {
        "schema_id": "tarka.vertical_holdout_promote/v1",
        "vertical": vertical,
        "pack_id": pack.get("id") or pid,
        "holdout_path": str(holdout_path(vertical)),
        "rows": len(y_true),
        "score_threshold": score_threshold,
        "metrics": metrics,
        "kill_gate": {k: v for k, v in kill.items() if k != "metrics"},
        "mcnemar_gate": mcn,
        "promote_allowed": promote_fixture,
        "promote_fixture_claim_allowed": promote_fixture,
        "promote_live_claim_allowed": False,
        "blockers": blockers,
        "champion": "always_allow",
        "challenger": "vertical_pack_score",
        "holdout_realism": realism,
        "honesty": (
            "Fixture-labeled holdout only — not LIVE tenant labels. "
            "promote_live_claim_allowed remains false. "
            "Synthetic F1 is software maturity, not detection proof."
        ),
    }


def load_all_vertical_promote_posture(
    *,
    verticals: tuple[str, ...] = _PRIORITY_VERTICALS,
) -> dict[str, Any]:
    packs = []
    for v in verticals:
        packs.append(evaluate_holdout_for_pack(v))
    any_fixture = any(p.get("promote_fixture_claim_allowed") for p in packs)
    return {
        "schema_id": "tarka.vertical_promote_ops/v1",
        "priority_verticals": list(verticals),
        "packs": packs,
        "promote_live_claim_allowed": False,
        "promote_fixture_claim_allowed": any_fixture,
        "all_priority_fixture_ok": all(
            p.get("promote_fixture_claim_allowed") for p in packs
        ),
        "honesty": (
            "LIVE promote claims stay false without vendor/LIVE labels; "
            "fixture claim is software maturity only."
        ),
    }


# Typology id → vertical affinity for ops by_vertical
_TYPOLOGY_VERTICAL: dict[str, str] = {
    "marketplace_lifecycle_abuse": "marketplace",
    "marketplace_ring_collusion": "marketplace",
    "marketplace_seller_trajectory": "marketplace",
    "marketplace_ftid": "marketplace",
    "marketplace_promo_economics": "marketplace",
    "marketplace_weak_representment": "marketplace",
    "marketplace_depth_fusion": "marketplace",
    "e_hailing_self_ride": "e_hailing",
    "e_hailing_pair_velocity": "e_hailing",
    "e_hailing_incentive_farm": "e_hailing",
    "e_hailing_account_rental": "e_hailing",
    "last_mile_ftid": "last_mile",
    "last_mile_pod_fail": "last_mile",
    "cod_fake_order_theft": "last_mile",
    "cod_address_abuse": "last_mile",
    "off_rail_payment": "marketplace",
    "velocity_abuse": "fintech",
    "new_payee_risk": "fintech",
    "amount_stress": "fintech",
}


def typology_ids_by_vertical() -> dict[str, list[str]]:
    from decision_api.typology import load_typology_definitions

    data = load_typology_definitions()
    out: dict[str, list[str]] = {}
    for spec in data.get("typologies") or []:
        tid = str(spec.get("id") or "")
        if not tid:
            continue
        vert = _TYPOLOGY_VERTICAL.get(tid, "shared")
        out.setdefault(vert, []).append(tid)
    for k in out:
        out[k] = sorted(out[k])
    return out
