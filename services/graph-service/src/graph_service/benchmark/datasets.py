from __future__ import annotations

"""Curated graph-fraud benchmark tasks (#64)."""


from typing import Any

BENCHMARK_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "binary_entity_high_risk",
        "name": "Binary entity high-risk ranking",
        "description": "Rank entities by risk score vs ground-truth high-risk label (precision/recall/AP).",
        "metrics_standard": ["precision", "recall", "average_precision", "latency_ms"],
        "label_space": "binary",
    },
    {
        "task_id": "fraud_ring_mule_detection",
        "name": "Fraud-ring / mule proximity",
        "description": "Evaluate graph-enhanced scores when ring-suspicion signals are present.",
        "metrics_standard": ["precision", "recall", "average_precision", "latency_ms"],
        "label_space": "binary",
    },
]


def list_tasks() -> dict[str, Any]:
    return {"schema": "tarka.graph_benchmark_tasks/v1", "tasks": list(BENCHMARK_TASKS)}


def get_task(task_id: str) -> dict[str, Any] | None:
    tid = (task_id or "").strip()
    for t in BENCHMARK_TASKS:
        if t["task_id"] == tid:
            return dict(t)
    return None
