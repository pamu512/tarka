"""Backtest-before-promote gate (Marble investigation-suite pattern / P2)."""

from __future__ import annotations

from typing import Any, Mapping

from decision_api.vertical_packs import evaluate_kill_criteria


def fixture_holdout_promote_gate(
    *,
    vertical: str,
    bind_when_labels_present: bool = True,
) -> dict[str, Any]:
    """Bind pack promote to labeled fixture F1 + McNemar when holdout exists.

    When no holdout file exists and ``bind_when_labels_present``, returns waived
    (simulation-metrics-only path). LIVE claim stays false.
    """
    from decision_api.vertical_promote_registry import (
        evaluate_holdout_for_pack,
        holdout_path,
    )

    if not holdout_path(vertical).is_file():
        return {
            "schema_id": "tarka.fixture_holdout_promote/v1",
            "vertical": vertical,
            "promote_allowed": True,
            "waived": True,
            "promote_live_claim_allowed": False,
            "promote_fixture_claim_allowed": False,
            "blockers": [],
            "note": "No labeled holdout file — fixture gate waived.",
        }
    if not bind_when_labels_present:
        return {
            "schema_id": "tarka.fixture_holdout_promote/v1",
            "vertical": vertical,
            "promote_allowed": True,
            "waived": True,
            "promote_live_claim_allowed": False,
            "promote_fixture_claim_allowed": False,
            "blockers": [],
            "note": "Fixture bind disabled by caller.",
        }
    result = evaluate_holdout_for_pack(vertical)
    return {
        "schema_id": "tarka.fixture_holdout_promote/v1",
        "vertical": vertical,
        "promote_allowed": bool(result.get("promote_allowed")),
        "waived": False,
        "promote_live_claim_allowed": False,
        "promote_fixture_claim_allowed": bool(
            result.get("promote_fixture_claim_allowed")
        ),
        "blockers": list(result.get("blockers") or []),
        "holdout": result,
        "note": "Labeled fixture holdout bound to pack kill_criteria + McNemar.",
    }


def metrics_from_backtest(metrics_json: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map warehouse backtest metrics_json → kill_criteria metrics."""
    m = metrics_json if isinstance(metrics_json, Mapping) else {}
    rows = int(m.get("rows_processed") or 0)
    return {
        "precision": float(m.get("precision") or 0.0),
        "recall": float(m.get("recall") or 0.0),
        "false_positive_rate": float(m.get("false_positive_rate") or 0.0),
        "f1_score": float(m.get("f1_score") or 0.0),
        "events_evaluated": rows,
        "decision_agreement_rate": m.get("decision_agreement_rate"),
        "true_positives": m.get("true_positives"),
        "false_positives": m.get("false_positives"),
        "false_negatives": m.get("false_negatives"),
    }


def backtest_before_promote_gate(
    *,
    job_status: str | None,
    metrics_json: Mapping[str, Any] | None,
    kill_criteria: Mapping[str, Any] | None,
    require_job: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Gate promote/install on a succeeded warehouse backtest + kill_criteria.

    When ``require_job`` is False and no ``job_id``, returns waived (compat with
    simulation-metrics-only install). When a job is supplied or required, the job
    must be ``succeeded`` and kill_criteria must pass on backtest metrics.
    """
    blockers: list[str] = []
    jid = (job_id or "").strip()
    if not jid:
        if require_job:
            blockers.append("backtest_job_id_required")
            return {
                "schema_id": "tarka.backtest_before_promote/v1",
                "promote_allowed": False,
                "blockers": blockers,
                "waived": False,
                "job_id": None,
                "job_status": None,
                "kill_gate": None,
                "metrics": None,
            }
        return {
            "schema_id": "tarka.backtest_before_promote/v1",
            "promote_allowed": True,
            "blockers": [],
            "waived": True,
            "job_id": None,
            "job_status": None,
            "kill_gate": None,
            "metrics": None,
            "note": "No backtest_job_id — using caller simulation metrics only.",
        }

    status = (job_status or "").strip().lower()
    if status != "succeeded":
        blockers.append(f"backtest_status_not_succeeded:{status or 'missing'}")
        return {
            "schema_id": "tarka.backtest_before_promote/v1",
            "promote_allowed": False,
            "blockers": blockers,
            "waived": False,
            "job_id": jid,
            "job_status": status or None,
            "kill_gate": None,
            "metrics": None,
        }

    metrics = metrics_from_backtest(metrics_json)
    kill = evaluate_kill_criteria(
        metrics,
        dict(kill_criteria) if kill_criteria else None,
        events_evaluated=int(metrics.get("events_evaluated") or 0),
    )
    if not kill.get("promote_allowed"):
        for b in kill.get("blockers") or []:
            blockers.append(str(b))
        if not kill.get("blockers"):
            blockers.append("backtest_kill_criteria_blocked")
    return {
        "schema_id": "tarka.backtest_before_promote/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "waived": False,
        "job_id": jid,
        "job_status": status,
        "kill_gate": {k: v for k, v in kill.items() if k != "metrics"},
        "metrics": metrics,
        "note": "Warehouse backtest metrics bound to pack kill_criteria.",
    }
