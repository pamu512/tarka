"""Directed evaluation DAG (Tier-1).

Validates a **static** dependency graph at import time (topological order + cycle detection).
At runtime, ``EvalDAGRuntime`` gates heavy steps (graph, ML, calibration) based on
adaptive load shedding and upstream step outcomes (``run_evaluation_step`` traces).
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

# child_step -> must have succeeded (trace["status"] == "ok") for each dependency.
# Steps not listed here are not DAG-gated by this module (or have no deps here).
STEP_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "counter_snapshot": ("feature_snapshot",),
    "location_eval": ("feature_snapshot",),
    "opa": ("feature_snapshot",),
    "ml_score": ("feature_snapshot",),
    "calibration_adjustment": ("opa", "ml_score"),
}


def _all_step_ids() -> frozenset[str]:
    nodes: set[str] = set()
    for child, deps in STEP_DEPENDENCIES.items():
        nodes.add(child)
        nodes.update(deps)
    return frozenset(nodes)


def validate_evaluation_dag() -> tuple[str, ...]:
    """Return a topological order of all nodes in ``STEP_DEPENDENCIES``.

    Raises:
        ValueError: if the graph contains a cycle.
    """
    nodes = _all_step_ids()
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    adj: dict[str, list[str]] = defaultdict(list)
    for child, deps in STEP_DEPENDENCIES.items():
        in_degree[child] = len(deps)
        for d in deps:
            adj[d].append(child)
    q = deque(sorted(n for n in nodes if in_degree[n] == 0))
    order: list[str] = []
    while q:
        u = q.popleft()
        order.append(u)
        for v in sorted(adj[u]):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                q.append(v)
    if len(order) != len(nodes):
        raise ValueError(
            "evaluation DAG cycle detected in STEP_DEPENDENCIES; fix eval_dag.py"
        )
    return tuple(order)


# Fail fast at import if operators misconfigure the static graph.
EVALUATION_DAG_TOPO_ORDER: tuple[str, ...] = validate_evaluation_dag()


class EvalDAGRuntime:
    """Runtime gates for evaluate; ``load_shed`` skips graph + ML; calibration requires OPA+ML ok."""

    __slots__ = ("load_shed",)

    def __init__(self, load_shed: bool) -> None:
        self.load_shed = load_shed

    def include_graph(self) -> bool:
        return not self.load_shed

    def include_ml(self, feature_snapshot_trace: dict[str, Any]) -> bool:
        if self.load_shed:
            return False
        return feature_snapshot_trace.get("status") == "ok"

    def include_calibration(
        self, opa_trace: dict[str, Any], ml_trace: dict[str, Any]
    ) -> bool:
        if self.load_shed:
            return False
        return opa_trace.get("status") == "ok" and ml_trace.get("status") == "ok"

    def ml_skip_reason(self, feature_snapshot_trace: dict[str, Any]) -> str:
        if self.load_shed:
            return "load_shedding"
        if feature_snapshot_trace.get("status") != "ok":
            return "skipped_due_to_dependency_failure"
        return "unknown"
