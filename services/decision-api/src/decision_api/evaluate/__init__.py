"""Evaluate pipeline package (ingress HTTP stays in ``decision_api.main``)."""

from decision_api.evaluate.score import (
    blend_scores,
    compute_fallback_reason,
    decision_runtime_status,
    signal_availability_notes_from_tags,
)

__all__ = [
    "blend_scores",
    "compute_fallback_reason",
    "decision_runtime_status",
    "signal_availability_notes_from_tags",
    "bind_main",
    "run_evaluate_decision",
]


def __getattr__(name: str):
    if name in ("bind_main", "run_evaluate_decision"):
        from decision_api.evaluate import pipeline as _pipeline

        return getattr(_pipeline, name)
    raise AttributeError(name)
