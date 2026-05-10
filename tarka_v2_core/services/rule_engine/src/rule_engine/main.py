"""FastAPI sidecar: evaluate a transaction against persisted or demo rules."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from ingestor.manifest_schema import TransactionSchema

from rule_engine.ast_schemas import Action, ConditionNode, FieldRef, Operator, Rule
from rule_engine.evaluator import evaluate_ruleset

logger = logging.getLogger(__name__)

# In-memory demo ruleset when no ``engine_rules`` rows exist (local dev / tests).
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


def _async_to_sync_database_url(url: str) -> str:
    u = url.strip()
    if u.startswith("sqlite+aiosqlite"):
        return u.replace("sqlite+aiosqlite", "sqlite+pysqlite", 1)
    if u.startswith("postgresql+asyncpg"):
        return u.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if u.startswith("postgres+asyncpg"):
        return u.replace("postgres+asyncpg", "postgresql+psycopg", 1)
    return u


def _rules_database_url() -> str | None:
    raw = (
        os.environ.get("RULE_ENGINE_DATABASE_URL")
        or os.environ.get("SHADOW_DATABASE_URL", "").strip()
        or os.environ.get("TARKA_AUDIT_DATABASE_URL", "").strip()
    )
    if not raw or ":memory:" in raw:
        return None
    return _async_to_sync_database_url(raw)


def load_active_ruleset() -> tuple[Rule, ...]:
    """Load rules from ``engine_rules`` when configured and rows exist; otherwise the demo ruleset."""
    url = _rules_database_url()
    if not url:
        return _DEMO_RULESET
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        logger.warning("sqlalchemy missing — using demo ruleset")
        return _DEMO_RULESET

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT definition FROM engine_rules"))
            rows = result.fetchall()
    except Exception:
        logger.exception("rule_engine_failed_to_read_engine_rules")
        return _DEMO_RULESET
    finally:
        engine.dispose()

    if not rows:
        return _DEMO_RULESET

    rules: list[Rule] = []
    for (definition,) in rows:
        payload = definition
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            logger.warning("rule_engine_skip_non_object_definition payload_type=%s", type(payload))
            continue
        try:
            rules.append(Rule.model_validate(payload))
        except Exception:
            logger.exception("rule_engine_skip_invalid_rule_definition")
    if not rules:
        return _DEMO_RULESET
    rules.sort(key=lambda r: r.priority)
    return tuple(rules)


def create_app() -> FastAPI:
    """Construct the ASGI application (separate from module-level ``app`` for tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ruleset = load_active_ruleset()
        yield

    application = FastAPI(
        title="tarka-rule-engine",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Liveness for orchestrator ``GET /health/full`` probes."""
        return {"status": "ok"}

    @application.post("/v1/evaluate")
    async def v1_evaluate(transaction: TransactionSchema, request: Request) -> dict[str, Any]:
        ruleset: tuple[Rule, ...] = getattr(request.app.state, "ruleset", _DEMO_RULESET)
        actions = evaluate_ruleset(ruleset, transaction)
        return {
            "actions": [a.value for a in actions],
            "transaction_id": str(transaction.entity_id),
        }

    @application.post("/v1/rules/reload")
    async def v1_rules_reload(request: Request) -> dict[str, Any]:
        """Reload the in-process rules cache from ``engine_rules`` (same DB URL as Shadow when shared)."""
        rs = load_active_ruleset()
        request.app.state.ruleset = rs
        return {"ok": True, "count": len(rs)}

    return application


app = create_app()
