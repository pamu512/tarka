"""FastAPI sidecar: evaluate a transaction against the built-in demo ruleset."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI
from ingestor.manifest_schema import TransactionSchema

from rule_engine.ast_schemas import Action, ConditionNode, FieldRef, Operator, Rule
from rule_engine.evaluator import evaluate_ruleset

# In-memory demo ruleset (replace with persistence later).
# Lower ``priority`` runs first. ``STRESS_BLOCK_LANE`` in ``metadata`` JSON yields a deterministic
# ``BLOCK`` for load tests (``scripts/stress_test_ingestion.py``); high amounts otherwise request
# ``SHADOW_REVIEW`` for the Shadow sidecar path.
_DEMO_RULESET: tuple[Rule, ...] = (
    Rule(
        id=UUID("00000000-0000-0000-0000-00000000c0de"),
        name="demo_stress_block_lane",
        root_node=ConditionNode(
            field=FieldRef(field="metadata"),
            operator=Operator.CONTAINS,
            value="STRESS_BLOCK_LANE",
        ),
        action=Action.BLOCK,
        priority=5,
    ),
    Rule(
        id=UUID("00000000-0000-0000-0000-00000000c0df"),
        name="demo_high_amount_shadow_review",
        root_node=ConditionNode(
            field=FieldRef(field="amount"),
            operator=Operator.GT,
            value=100.0,
        ),
        action=Action.SHADOW_REVIEW,
        priority=10,
    ),
)


def create_app() -> FastAPI:
    """Construct the ASGI application (separate from module-level ``app`` for tests)."""
    application = FastAPI(
        title="tarka-rule-engine",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.post("/v1/evaluate")
    async def v1_evaluate(transaction: TransactionSchema) -> dict[str, Any]:
        actions = evaluate_ruleset(_DEMO_RULESET, transaction)
        return {
            "actions": [a.value for a in actions],
            "transaction_id": str(transaction.entity_id),
        }

    return application


app = create_app()
