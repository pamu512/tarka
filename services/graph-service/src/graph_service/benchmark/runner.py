from __future__ import annotations

import json
import random
import time
import uuid
from hashlib import sha256
from typing import Any

from graph_service.benchmark.datasets import get_task
from graph_service.benchmark.metrics import average_precision_binary, precision_recall

"""Reproducible graph vs baseline experiment runner and scorecard (#66)."""

def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def promotion_summary(
    *,
    baseline_ap: float,
    graph_ap: float,
    baseline_prec: float,
    graph_prec: float,
    ap_lift_min: float = 0.02,
    prec_drop_max: float = 0.03,
) -> dict[str, Any]:
    ap_delta = round(graph_ap - baseline_ap, 6)
    prec_delta = round(graph_prec - baseline_prec, 6)
    if ap_delta >= ap_lift_min and prec_delta >= -prec_drop_max:
        decision = "promote_graph_enhanced"
        rationale = "Graph-enhanced AP improved materially without unacceptable precision loss."
    elif ap_delta < 0 and graph_ap < baseline_ap * 0.95:
        decision = "rollback_graph_enhanced"
        rationale = "Graph-enhanced scores materially underperform baseline."
    else:
        decision = "hold"
        rationale = "Insufficient lift or mixed precision trade-off; collect more data or tune."
    return {
        "decision": decision,
        "ap_delta": ap_delta,
        "precision_delta": prec_delta,
        "rationale": rationale,
    }


def run_experiment(
    *,
    seed: int,
    task_id: str,
    y_true: list[int],
    baseline_scores: list[float],
    graph_scores: list[float],
) -> dict[str, Any]:
    """Fixed-seed scorecard: metrics for baseline vs graph-enhanced vectors."""
    if not get_task(task_id):
        raise ValueError(f"unknown_task:{task_id}")
    n = len(y_true)
    if len(baseline_scores) != n or len(graph_scores) != n:
        raise ValueError("y_true, baseline_scores, and graph_scores must have equal length")

    rnd = random.Random(int(seed))
    # Deterministic micro-shuffle of tie order (reproducibility hook).
    order = list(range(n))
    rnd.shuffle(order)

    t0 = time.perf_counter()
    b_prec, b_rec = precision_recall(y_true, baseline_scores)
    g_prec, g_rec = precision_recall(y_true, graph_scores)
    b_ap = average_precision_binary(y_true, baseline_scores)
    g_ap = average_precision_binary(y_true, graph_scores)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    metrics_block = {
        "baseline": {"precision": b_prec, "recall": b_rec, "average_precision": b_ap},
        "graph_enhanced": {"precision": g_prec, "recall": g_rec, "average_precision": g_ap},
    }
    artifact_digest = _digest(
        {
            "task_id": task_id,
            "seed": seed,
            "y_true": y_true,
            "baseline_scores": baseline_scores,
            "graph_scores": graph_scores,
            "metrics": metrics_block,
        },
    )
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tarka.graph-benchmark|{artifact_digest}"))
    scorecard = {
        "schema": "tarka.graph_benchmark_scorecard/v1",
        "run_id": run_id,
        "task_id": task_id,
        "seed": int(seed),
        "n": n,
        "order_digest": sha256(json.dumps(order).encode()).hexdigest()[:16],
        "baseline": metrics_block["baseline"],
        "graph_enhanced": metrics_block["graph_enhanced"],
        "latency_ms": latency_ms,
        "promotion": promotion_summary(
            baseline_ap=b_ap,
            graph_ap=g_ap,
            baseline_prec=b_prec,
            graph_prec=g_prec,
        ),
        "artifact_digest": artifact_digest,
    }
    return scorecard
