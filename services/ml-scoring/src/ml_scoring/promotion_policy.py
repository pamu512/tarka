from __future__ import annotations

"""Versioned ML promotion gate (OSS #37) — evaluate model metadata against ml_promotion_policy_v1.json."""


import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def policy_path_for_models_dir(models_dir: Path) -> Path:
    return models_dir.resolve().parent / "rules" / "ml_promotion_policy_v1.json"


def read_promotion_policy(models_dir: Path) -> dict[str, Any]:
    """Load policy JSON; permissive defaults if file missing (dev/test)."""
    p = policy_path_for_models_dir(models_dir)
    if not p.is_file():
        log.warning("promotion policy missing %s — using permissive defaults", p)
        return {
            "policy_id": "default",
            "version": 0,
            "min_training_auc_roc": 0.0,
            "max_training_latency_p99_ms": None,
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("failed to load promotion policy: %s", e)
        return {
            "policy_id": "default",
            "version": 0,
            "min_training_auc_roc": 0.0,
            "max_training_latency_p99_ms": None,
        }


def evaluate_version_gate(
    policy: dict[str, Any],
    *,
    model_name: str,
    version: int,
    metadata: dict[str, Any],
    framework: str = "",
) -> tuple[bool, list[str], dict[str, Any]]:
    """Return (passes, human reasons, report artifact for audit/CI)."""
    fw = (framework or "").lower()
    if fw == "heuristic":
        return True, [], {"skipped": "heuristic_baseline", "model": model_name, "version": version}

    reasons: list[str] = []
    checks: dict[str, Any] = {}
    min_auc = float(policy.get("min_training_auc_roc") or 0.0)
    tm = metadata.get("training_metrics")
    auc: float | None = None
    if isinstance(tm, dict) and tm.get("auc_roc") is not None:
        try:
            auc = float(tm["auc_roc"])
        except (TypeError, ValueError):
            auc = None
    checks["auc_roc"] = {"min_required": min_auc, "value": auc}
    if min_auc > 0:
        if auc is None:
            reasons.append(f"missing training_metrics.auc_roc (required min {min_auc})")
        elif auc < min_auc:
            reasons.append(f"training_metrics.auc_roc {auc} < policy minimum {min_auc}")

    max_lat = policy.get("max_training_latency_p99_ms")
    if max_lat is not None:
        try:
            cap = float(max_lat)
        except (TypeError, ValueError):
            cap = None
        if cap is not None and isinstance(tm, dict):
            lat = tm.get("latency_p99_ms")
            try:
                lat_f = float(lat) if lat is not None else None
            except (TypeError, ValueError):
                lat_f = None
            checks["latency_p99_ms"] = {"max_allowed": cap, "value": lat_f}
            if lat_f is None:
                reasons.append(f"missing training_metrics.latency_p99_ms (required max {cap} ms)")
            elif lat_f > cap:
                reasons.append(f"training_metrics.latency_p99_ms {lat_f} > policy max {cap} ms")

    # Champion vs challenger golden-set / benchmark guardrails (OSS #37 / #52).
    # Expect training_metrics.benchmark_vs_champion with optional fp_rate_delta, recall_lift, latency_p95_ms.
    bench: dict[str, Any] | None = None
    if isinstance(tm, dict):
        b = tm.get("benchmark_vs_champion")
        bench = b if isinstance(b, dict) else None

    max_fp_delta = policy.get("max_fp_rate_delta_vs_champion")
    if max_fp_delta is not None:
        try:
            fp_cap = float(max_fp_delta)
        except (TypeError, ValueError):
            fp_cap = None
        if fp_cap is not None:
            fp_val: float | None = None
            if bench and bench.get("fp_rate_delta") is not None:
                try:
                    fp_val = float(bench["fp_rate_delta"])
                except (TypeError, ValueError):
                    fp_val = None
            checks["fp_rate_delta_vs_champion"] = {"max_allowed": fp_cap, "value": fp_val}
            if fp_val is None:
                reasons.append(
                    f"missing training_metrics.benchmark_vs_champion.fp_rate_delta (required max delta {fp_cap})",
                )
            elif fp_val > fp_cap:
                reasons.append(
                    f"benchmark fp_rate_delta {fp_val} exceeds policy max_fp_rate_delta_vs_champion {fp_cap}",
                )

    min_lift = policy.get("min_recall_lift_vs_champion")
    if min_lift is not None:
        try:
            lift_min = float(min_lift)
        except (TypeError, ValueError):
            lift_min = None
        if lift_min is not None:
            lift_val: float | None = None
            if bench and bench.get("recall_lift") is not None:
                try:
                    lift_val = float(bench["recall_lift"])
                except (TypeError, ValueError):
                    lift_val = None
            checks["recall_lift_vs_champion"] = {"min_required": lift_min, "value": lift_val}
            if lift_val is None:
                reasons.append(
                    f"missing training_metrics.benchmark_vs_champion.recall_lift (required min {lift_min})",
                )
            elif lift_val < lift_min:
                reasons.append(
                    f"benchmark recall_lift {lift_val} < policy min_recall_lift_vs_champion {lift_min}",
                )

    max_bench_lat = policy.get("max_benchmark_latency_p95_ms")
    if max_bench_lat is not None:
        try:
            lat_cap = float(max_bench_lat)
        except (TypeError, ValueError):
            lat_cap = None
        if lat_cap is not None:
            b_lat: float | None = None
            if bench and bench.get("latency_p95_ms") is not None:
                try:
                    b_lat = float(bench["latency_p95_ms"])
                except (TypeError, ValueError):
                    b_lat = None
            checks["benchmark_latency_p95_ms"] = {"max_allowed": lat_cap, "value": b_lat}
            if b_lat is None:
                reasons.append(
                    f"missing training_metrics.benchmark_vs_champion.latency_p95_ms (required max {lat_cap} ms)",
                )
            elif b_lat > lat_cap:
                reasons.append(
                    f"benchmark latency_p95_ms {b_lat} > policy max_benchmark_latency_p95_ms {lat_cap} ms",
                )

    report = {
        "policy_id": policy.get("policy_id", "unknown"),
        "policy_version": policy.get("version", 0),
        "model": model_name,
        "version": version,
        "passes": len(reasons) == 0,
        "checks": checks,
        "reasons": reasons,
    }
    return len(reasons) == 0, reasons, report
