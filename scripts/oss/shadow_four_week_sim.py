#!/usr/bin/env python3
"""Four-week shadow vs host-action synthetic chronological dry-run.

Wiring/smoke only — output banner is NOT PRODUCTION L3. Does not satisfy L3
claim lock. See docs/superpowers/playbooks/2026-08-05-shadow-four-week-critical.md.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_OUT = _REPO / "artifacts" / "shadow_four_week_sim.json"
BANNER = "NOT PRODUCTION L3"
_SCHEMA = "tarka.shadow_four_week_sim/v1"
_EVENTS_PER_WEEK = 400


def _confusion(
    rng: random.Random,
    *,
    shadow_tpr: float,
    shadow_fpr: float,
    host_tpr: float,
    host_fpr: float,
    fraud_rate: float,
    insult_on_fp_rate: float,
) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    insult_events = 0
    for _ in range(_EVENTS_PER_WEEK):
        is_fraud = rng.random() < fraud_rate
        shadow_flag = rng.random() < (shadow_tpr if is_fraud else shadow_fpr)
        host_flag = rng.random() < (host_tpr if is_fraud else host_fpr)
        if shadow_flag and is_fraud:
            tp += 1
        elif shadow_flag and not is_fraud:
            fp += 1
            if rng.random() < insult_on_fp_rate:
                insult_events += 1
        elif not shadow_flag and is_fraud:
            fn += 1
        else:
            tn += 1
    denom_p = tp + fp
    denom_r = tp + fn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / denom_p if denom_p else 0.0,
        "recall": tp / denom_r if denom_r else 0.0,
        "insult_events": insult_events,
        "events_evaluated": _EVENTS_PER_WEEK,
    }


def _simulate_week(
    rng: random.Random,
    *,
    week_index: int,
    week_start: datetime,
    kill_criteria: dict[str, Any] | None,
) -> dict[str, Any]:
    # Slight drift week-over-week so the run is visibly chronological, not flat.
    drift = 0.01 * week_index
    block = _confusion(
        rng,
        shadow_tpr=min(0.92, 0.78 + drift),
        shadow_fpr=max(0.04, 0.11 - drift * 0.5),
        host_tpr=min(0.90, 0.74 + drift),
        host_fpr=max(0.05, 0.12 - drift * 0.4),
        fraud_rate=0.075 + drift * 0.2,
        insult_on_fp_rate=0.22,
    )
    week_end = week_start + timedelta(days=7)
    insult_proxy = block["insult_events"] / block["fp"] if block["fp"] else 0.0
    promote_gate: dict[str, Any] | None = None
    if kill_criteria is not None:
        sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))
        from decision_api.vertical_packs import evaluate_kill_criteria

        fpr = block["fp"] / max(block["fp"] + block["tn"], 1)
        promote_gate = evaluate_kill_criteria(
            {
                "precision": block["precision"],
                "recall": block["recall"],
                "false_positive_rate": fpr,
            },
            kill_criteria,
            events_evaluated=block["events_evaluated"],
        )
    return {
        "week": week_index + 1,
        "start": week_start.isoformat(),
        "end": week_end.isoformat(),
        "precision": round(block["precision"], 6),
        "recall": round(block["recall"], 6),
        "insult_proxy": round(insult_proxy, 6),
        "events_evaluated": block["events_evaluated"],
        "tp": block["tp"],
        "fp": block["fp"],
        "fn": block["fn"],
        "insult_events": block["insult_events"],
        "promote_gate": promote_gate,
    }


def run_sim(*, seed: int, out_path: Path) -> dict[str, Any]:
    rng = random.Random(seed)
    sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))
    from decision_api.vertical_packs import get_vertical_pack

    pack = get_vertical_pack("fintech") or {}
    kill = pack.get("kill_criteria")
    start = datetime(2026, 1, 5, tzinfo=UTC)
    weeks: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = 0
    total_insult = 0
    for i in range(4):
        week_start = start + timedelta(weeks=i)
        week = _simulate_week(rng, week_index=i, week_start=week_start, kill_criteria=kill)
        total_tp += week["tp"]
        total_fp += week["fp"]
        total_fn += week["fn"]
        total_insult += week["insult_events"]
        weeks.append({k: v for k, v in week.items() if k not in {"tp", "fp", "fn", "insult_events"}})

    denom_p = total_tp + total_fp
    denom_r = total_tp + total_fn
    precision = total_tp / denom_p if denom_p else 0.0
    recall = total_tp / denom_r if denom_r else 0.0
    insult_proxy = total_insult / total_fp if total_fp else 0.0

    artifact: dict[str, Any] = {
        "schema_id": _SCHEMA,
        "banner": BANNER,
        "mode": "synthetic_dry_run",
        "seed": seed,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "disclaimer": (
            "Synthetic four-week chronological dry-run for wiring/smoke. "
            "Does not constitute live L3 evidence or production shadow ops proof."
        ),
        "weeks": weeks,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "insult_proxy": round(insult_proxy, 6),
        "events_evaluated": sum(w["events_evaluated"] for w in weeks),
        "promote_gate_week4": weeks[-1].get("promote_gate"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output JSON path (default: {_DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)
    artifact = run_sim(seed=args.seed, out_path=args.out)
    if artifact.get("banner") != BANNER:
        print("shadow_four_week_sim: FAIL — banner missing or wrong", file=sys.stderr)
        return 1
    print(
        f"shadow_four_week_sim: OK banner={artifact['banner']} "
        f"precision={artifact['precision']:.4f} recall={artifact['recall']:.4f} "
        f"insult_proxy={artifact['insult_proxy']:.4f} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
