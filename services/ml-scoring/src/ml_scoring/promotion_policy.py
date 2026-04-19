"""Versioned ML promotion gate (OSS #37) — evaluate model metadata against ml_promotion_policy_v1.json."""

from __future__ import annotations

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
