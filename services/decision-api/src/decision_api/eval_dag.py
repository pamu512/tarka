"""Directed evaluation DAG (Tier-1 orchestration).

Heavy dependencies (graph-service, ML) are optional nodes toggled by adaptive
load shedding and tenant flags; the ordered backbone is:
lists → consortium → graph_risk → feature_snapshot → counters → location →
external_signals → rules → OPA/ML (parallel) → calibration → persist.
"""


from __future__ import annotations


class EvalDAG:
    """Minimal DAG gate used by ``evaluate_decision`` for conditional heavy steps."""

    __slots__ = ("load_shed",)

    def __init__(self, load_shed: bool) -> None:
        self.load_shed = load_shed

    def include_graph(self) -> bool:
        return not self.load_shed

    def include_ml(self) -> bool:
        return not self.load_shed
