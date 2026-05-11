"""HTTP surface for rule evaluation (panic-safe)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tarka_rule_engine._wrapper import RuleEngine

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_evaluate_app() -> "FastAPI":
    """Construct a small FastAPI app: ``POST /v1/evaluate`` → JSON including ``decision``."""
    try:
        from fastapi import Body, FastAPI
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "HTTP API requires optional dependencies; install with: pip install 'tarka-rule-engine[api]'"
        ) from exc

    app = FastAPI(title="tarka-rule-engine", version="0.1.0")

    @app.post("/v1/evaluate")
    def v1_evaluate(
        payload: dict[str, Any] = Body(
            ...,
            examples=[{"graph_score": 0.25, "velocity_1h": 3}],
        ),
    ) -> dict[str, Any]:
        graph_score = float(payload.get("graph_score", 0.0))
        velocity_1h = int(payload.get("velocity_1h", 0))
        eng = RuleEngine()
        return eng.evaluate(graph_score, velocity_1h)

    return app
