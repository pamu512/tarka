"""FastAPI sidecar: evaluate a transaction against persisted or demo rules."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from ingestor.manifest_schema import TransactionSchema
from pydantic import BaseModel, ConfigDict, Field

from rule_engine.ast_schemas import Action, ConditionNode, FieldRef, Operator, Rule
from rule_engine.evaluator import evaluate_ruleset_detailed
from rule_engine.graph_context import (
    GRAPH_CONTEXT_FAIL_OPEN_KEY,
    GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD,
    Neo4jGraphContextProvider,
    NullGraphContextProvider,
    ruleset_needs_graph_context,
)
from rule_engine.hetu_timeouts import graph_context_fetch_timeout_sec
from rule_engine.rules_store import (
    deploy_new_rules_version,
    load_rules_from_db,
    open_rules_engine,
    rules_database_url,
)

logger = logging.getLogger(__name__)

_GRAPH_PROVIDER_UNSET = object()

# In-memory demo ruleset when no ``fraud_rules`` / ``engine_rules`` rows exist (local dev / tests).
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


def load_active_ruleset() -> tuple[Rule, ...]:
    """Load rules from ``fraud_rules`` (active version), else ``engine_rules``, else the demo ruleset."""
    engine = open_rules_engine()
    if engine is None:
        return _DEMO_RULESET
    try:
        loaded = load_rules_from_db(engine)
        if loaded is not None:
            return loaded
    except Exception:
        logger.exception("rule_engine_failed_load_rules")
    finally:
        engine.dispose()
    return _DEMO_RULESET


class RulesDeployBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Validated :class:`~rule_engine.ast_schemas.Rule` objects as JSON dicts.",
    )


class RulesDeployResponse(BaseModel):
    ok: bool = True
    version: int
    rule_count: int


def create_app(*, graph_context_provider: object = _GRAPH_PROVIDER_UNSET) -> FastAPI:
    """Construct the ASGI application.

    Parameters:
        graph_context_provider: Optional override for tests. ``_GRAPH_PROVIDER_UNSET`` (default)
            picks :class:`~rule_engine.graph_context.Neo4jGraphContextProvider` from env or falls
            back to :class:`~rule_engine.graph_context.NullGraphContextProvider`. Pass ``None`` for
            an explicit no-op provider.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ruleset = load_active_ruleset()
        if graph_context_provider is _GRAPH_PROVIDER_UNSET:
            neo = Neo4jGraphContextProvider.try_from_env()
            app.state.graph_context_provider = neo if neo is not None else NullGraphContextProvider()
        elif graph_context_provider is None:
            app.state.graph_context_provider = NullGraphContextProvider()
        else:
            app.state.graph_context_provider = graph_context_provider
        yield
        prov = getattr(app.state, "graph_context_provider", None)
        if isinstance(prov, Neo4jGraphContextProvider):
            try:
                await prov.close()
            except Exception:
                logger.exception("rule_engine_neo4j_provider_close_failed")

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
        graph_ctx: dict[str, Any] | None = None
        graph_fail_open = False
        if ruleset_needs_graph_context(ruleset):
            prov = getattr(request.app.state, "graph_context_provider", None)
            if prov is None:
                prov = NullGraphContextProvider()
            timeout_sec = graph_context_fetch_timeout_sec()
            if timeout_sec is None:
                graph_ctx = await prov.fetch_graph_context(transaction)
            else:
                try:
                    graph_ctx = await asyncio.wait_for(
                        prov.fetch_graph_context(transaction),
                        timeout=timeout_sec,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "rule_engine_graph_context_fetch_timeout fail_open entity_id=%s timeout_sec=%s",
                        transaction.entity_id,
                        timeout_sec,
                    )
                    graph_ctx = {
                        GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD: 0,
                        GRAPH_CONTEXT_FAIL_OPEN_KEY: True,
                    }
            graph_fail_open = bool(graph_ctx.get(GRAPH_CONTEXT_FAIL_OPEN_KEY)) if graph_ctx else False
            graph_ctx_eval = (
                {k: v for k, v in graph_ctx.items() if not str(k).startswith("_")}
                if graph_ctx
                else None
            )
            logger.info(
                "rule_engine_graph_context graph_linked_to_blocked_count=%s entity_id=%s fail_open=%s",
                (graph_ctx_eval or {}).get("graph_linked_to_blocked_count"),
                transaction.entity_id,
                graph_fail_open,
            )
        else:
            graph_ctx_eval = None
        detail = evaluate_ruleset_detailed(ruleset, transaction, graph_context=graph_ctx_eval)
        return {
            "actions": [a.value for a in detail.actions],
            "transaction_id": str(transaction.entity_id),
            "evaluation_trace": detail.trace,
            "blocking_rule_id": detail.blocking_rule_id,
            "graph_context_fail_open": graph_fail_open,
        }

    @application.post("/v1/rules/reload")
    async def v1_rules_reload(request: Request) -> dict[str, Any]:
        """Reload the in-process rules cache from ``fraud_rules`` (active row) or legacy ``engine_rules``."""
        rs = load_active_ruleset()
        request.app.state.ruleset = rs
        return {"ok": True, "count": len(rs)}

    @application.post("/v1/rules/deploy")
    async def v1_rules_deploy(body: RulesDeployBody, request: Request) -> RulesDeployResponse:
        """
        Append a new immutable ``fraud_rules`` version and make it active (previous rows unchanged).
        """
        if rules_database_url() is None:
            raise HTTPException(
                status_code=422,
                detail="RULE_ENGINE_DATABASE_URL (or SHADOW_DATABASE_URL / TARKA_AUDIT_DATABASE_URL) "
                "required for deploy",
            )

        def _run() -> tuple[int, int]:
            engine = open_rules_engine()
            assert engine is not None
            try:
                validated = [Rule.model_validate(r) for r in body.rules]
                ver = deploy_new_rules_version(engine, validated)
                return ver, len(validated)
            finally:
                engine.dispose()

        try:
            version, n = await asyncio.to_thread(_run)
        except Exception:
            logger.exception("rule_engine_deploy_failed")
            raise HTTPException(status_code=500, detail="deploy failed") from None

        request.app.state.ruleset = load_active_ruleset()
        return RulesDeployResponse(version=version, rule_count=n)

    return application
