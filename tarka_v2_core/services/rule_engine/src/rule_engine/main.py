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
    activate_fraud_rules_version,
    deploy_new_rules_version,
    get_fraud_rules_version_payload,
    list_fraud_rules_versions,
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
    promotion_feedback: list[dict[str, Any]] | None = None


class RuleVersionSummary(BaseModel):
    version: int
    is_active: bool
    rule_count: int
    created_at: str | None = None
    ast_hash: str


class RulesVersionsResponse(BaseModel):
    versions: list[RuleVersionSummary]
    active_version: int | None = None
    source: str = "fraud_rules"


class RulesRollbackResponse(BaseModel):
    ok: bool = True
    active_version: int
    rule_count: int
    reloaded: bool = True


class HypothesisDeployBody(BaseModel):
    """Shadow observation rules for hot-reload into the Rust engine (Prompt 192)."""

    model_config = ConfigDict(extra="forbid")

    rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="JSON rules with metadata.is_shadow=true (when / when_ast).",
    )
    tenant_id: str = Field(default="default", max_length=128)
    version: int | None = Field(default=None, ge=1)


class HypothesisDeployResponse(BaseModel):
    ok: bool = True
    redis_key: str
    rule_count: int
    nats_subject: str | None = None
    version: int | None = None


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

    @application.get("/v1/rules/versions", response_model=RulesVersionsResponse)
    async def v1_rules_versions() -> RulesVersionsResponse:
        """List immutable AST snapshots in ``fraud_rules`` (newest first)."""
        if rules_database_url() is None:
            return RulesVersionsResponse(versions=[], active_version=None, source="unconfigured")

        def _run() -> RulesVersionsResponse:
            engine = open_rules_engine()
            assert engine is not None
            try:
                raw = list_fraud_rules_versions(engine)
            finally:
                engine.dispose()
            versions = [RuleVersionSummary.model_validate(v) for v in raw]
            active = next((v.version for v in versions if v.is_active), None)
            return RulesVersionsResponse(versions=versions, active_version=active)

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            logger.exception("rule_engine_list_versions_failed")
            raise HTTPException(status_code=500, detail="list versions failed") from None

    @application.get("/v1/rules/versions/{version}")
    async def v1_rules_version_detail(version: int) -> dict[str, Any]:
        """Fetch one immutable AST snapshot (full ``rules_payload``)."""
        if rules_database_url() is None:
            raise HTTPException(status_code=422, detail="rules database not configured")

        def _run() -> dict[str, Any] | None:
            engine = open_rules_engine()
            assert engine is not None
            try:
                return get_fraud_rules_version_payload(engine, version)
            finally:
                engine.dispose()

        try:
            row = await asyncio.to_thread(_run)
        except Exception:
            logger.exception("rule_engine_version_detail_failed")
            raise HTTPException(status_code=500, detail="version detail failed") from None
        if row is None:
            raise HTTPException(status_code=404, detail=f"version {version} not found")
        return row

    @application.post("/v1/rules/rollback/{version}", response_model=RulesRollbackResponse)
    async def v1_rules_rollback(version: int, request: Request) -> RulesRollbackResponse:
        """Activate a prior ``fraud_rules`` AST snapshot and hot-reload the in-process ruleset."""
        if rules_database_url() is None:
            raise HTTPException(
                status_code=422,
                detail="RULE_ENGINE_DATABASE_URL (or SHADOW_DATABASE_URL / TARKA_AUDIT_DATABASE_URL) "
                "required for rollback",
            )

        def _run() -> tuple[int, int]:
            engine = open_rules_engine()
            assert engine is not None
            try:
                activate_fraud_rules_version(engine, version)
                active = load_rules_from_db(engine)
                n = len(active) if active is not None else 0
                return version, n
            finally:
                engine.dispose()

        try:
            ver, n = await asyncio.to_thread(_run)
        except LookupError:
            raise HTTPException(status_code=404, detail=f"version {version} not found") from None
        except Exception:
            logger.exception("rule_engine_rollback_failed")
            raise HTTPException(status_code=500, detail="rollback failed") from None

        request.app.state.ruleset = load_active_ruleset()
        return RulesRollbackResponse(active_version=ver, rule_count=n)

    @application.post("/v1/rules/reload")
    async def v1_rules_reload(request: Request) -> dict[str, Any]:
        """Reload the in-process rules cache from ``fraud_rules`` (active row) or legacy ``engine_rules``."""
        rs = load_active_ruleset()
        request.app.state.ruleset = rs
        return {"ok": True, "count": len(rs)}

    @application.post("/v1/rules/deploy", response_model_exclude_none=True)
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

        from rule_engine.promotion_feedback import (
            emit_observation_promotion_feedback,
            is_observation_promotion,
        )

        promotion_feedback: list[dict[str, Any]] = []
        for raw in body.rules:
            if not isinstance(raw, dict) or not is_observation_promotion(raw):
                continue
            try:
                fb = await emit_observation_promotion_feedback(
                    raw,
                    rule_version=version,
                )
                promotion_feedback.append(fb)
            except Exception:
                logger.exception(
                    "rule_engine_promotion_feedback_failed rule_id=%s",
                    raw.get("id"),
                )

        return RulesDeployResponse(
            version=version,
            rule_count=n,
            promotion_feedback=promotion_feedback or None,
        )

    @application.post("/v1/hypotheses/deploy")
    async def v1_hypotheses_deploy(body: HypothesisDeployBody) -> HypothesisDeployResponse:
        """
        Deploy active shadow hypotheses to Redis and publish NATS ``hypothesis_deployed``.

        The Rust ``tarka-rule-engine-watcher`` reloads its in-memory ruleset via a ``watch`` channel.
        """
        from rule_engine.hypothesis_deploy import publish_hypothesis_deployed

        for i, rule in enumerate(body.rules):
            meta = rule.get("metadata")
            if not isinstance(meta, dict) or meta.get("is_shadow") is not True:
                raise HTTPException(
                    status_code=422,
                    detail=f"rules[{i}].metadata.is_shadow must be true for hypothesis deploy",
                )

        try:
            out = await publish_hypothesis_deployed(
                rules=body.rules,
                tenant_id=body.tenant_id,
                version=body.version,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception:
            logger.exception("hypothesis_deploy_failed")
            raise HTTPException(status_code=500, detail="hypothesis deploy failed") from None

        return HypothesisDeployResponse(
            redis_key=str(out["redis_key"]),
            rule_count=int(out["rule_count"]),
            nats_subject=out.get("nats_subject"),
            version=body.version,
        )

    return application
