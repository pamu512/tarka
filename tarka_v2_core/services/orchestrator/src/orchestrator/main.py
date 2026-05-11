"""FastAPI ingestion gateway: rule engine first, then conditional Shadow AI analyze."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from ingestor.manifest_schema import TransactionSchema
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from tarka_shared.database.session import Base

from orchestrator.ai_feedback_jsonl import append_feedback_jsonl, resolve_ai_feedback_jsonl_path
from orchestrator.analytics.deps import get_analytics
from orchestrator.analytics.factory import build_analytics_provider
from orchestrator.analytics.provider import AnalyticsProvider
from orchestrator.anumana_browser_ingest import handle_browser_telemetry_ingest
from orchestrator.audit_case_worker import (
    build_audit_engine,
    process_new_audit_logs,
    resolve_audit_database_url,
)
from orchestrator.case_export import CaseExportNotFoundError, build_compliance_export_zip
from orchestrator.case_transition_api import put_lifecycle_case_status
from orchestrator.dispute_evidence_pdf import PDF_GRAPH_SECTION_TITLE
from orchestrator.dispute_lock_export import (
    FILE_DISPUTE_LOCK_REASON,
    build_dispute_evidence_pdf_for_case,
)
from orchestrator.disputes.chargeback_inception import (
    build_chargeback_transaction,
    resolve_linked_session_id,
)
from orchestrator.entity_profile import build_entity_profile_payload
from orchestrator.graph.client import GraphClient, graph_client_from_environment
from orchestrator.ingestion_schema import IngestionSchema
from orchestrator.investigation_cluster_shadow import (
    build_prime_shadow_graph_context,
    synthetic_dispute_transaction,
)
from orchestrator.investigation_knowledge import knowledge_bundle_for_detected_ids
from orchestrator.investigation_prime import prime_from_upload
from orchestrator.models.cases import CaseStatus
from orchestrator.openapi_schemas import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    AnalyticsTransactionsSnapshot,
    AnalyticsVelocityResponse,
    AnalyticsVelocityRow,
    BadGateway502,
    CaseStatusUpdateRequest,
    CaseStatusUpdateResponse,
    ChargebackIngestRequest,
    DemoSimulateResponse,
    EntityProfileResponse,
    HealthFullResponse,
    HTTPValidationError422,
    IngestResponse,
    InvestigationPrimeResponse,
    RuleShadowTestRequest,
    RuleShadowTestResponse,
    ServiceUnavailable503,
)
from orchestrator.rule_shadow_test import execute_rule_shadow_test
from orchestrator.transaction_ingest import execute_transaction_ingest

logger = logging.getLogger(__name__)

_ORCHESTRATOR_DESCRIPTION = """\
Public gateway for submitting **transaction envelopes** and retrieving combined outcomes.

## Transaction body (`TransactionSchema`)

All ingestion requests must provide:

| Field | Requirement |
|-------|-------------|
| **entity_id** | UUID identifying the transaction |
| **amount** | Finite number strictly greater than zero |
| **timestamp** | ISO 8601 datetime |
| **metadata** | JSON object (optional; default `{}`). Arbitrary keys allowed **inside** `metadata` only. |

The top-level JSON object **must not** include fields other than these four (`extra` is forbidden). \
Unknown keys at the root are rejected with **422** validation errors.

## Behavior overview

1. The orchestrator forwards your envelope to the policy tier and returns its structured outcome.
2. If that outcome requests secondary fraud review, the orchestrator may invoke an analysis tier \
and merge its structured result when available.

Responses never embed internal service URLs or hop-by-hop routing configuration.
"""

_ORCHESTRATOR_TAGS: list[dict[str, str]] = [
    {
        "name": "Ingestion",
        "description": (
            "Submit canonical transaction envelopes. Responses combine rule outcomes with "
            "optional secondary analysis when policy requests it."
        ),
    },
    {
        "name": "Operations",
        "description": "Readiness and dependency probes for orchestration and dashboards.",
    },
    {
        "name": "Demo",
        "description": "Non-production helpers for UI simulations.",
    },
    {
        "name": "Investigation",
        "description": "Analyst workspace helpers (document priming for Shadow review).",
    },
    {
        "name": "Rules",
        "description": "Offline rule validation before persisting definitions to ``engine_rules``.",
    },
    {
        "name": "Analytics",
        "description": "Local DuckDB-backed rollups for ops dashboards (seed Parquet on startup).",
    },
    {
        "name": "Marketplace",
        "description": "Operator-facing entity views (graph + analytics + case status).",
    },
    {
        "name": "Cases",
        "description": "Lifecycle investigation case transitions and audit history.",
    },
    {
        "name": "Anumana",
        "description": (
            "Redis hot-path for browser SDK telemetry (``POST /ingest``) — no graph write on this route."
        ),
    },
    {
        "name": "AI",
        "description": "Analyst feedback capture for model improvement (local JSONL export).",
    },
]

_RESP_422 = {
    422: {
        "model": HTTPValidationError422,
        "description": (
            "Request body failed validation: missing required fields, invalid types, "
            "non-finite amount, or extra top-level keys on the transaction envelope."
        ),
    },
}

_RESP_INGEST = {
    **_RESP_422,
    502: {
        "model": BadGateway502,
        "description": "An upstream tier returned an HTTP error or an unexpected payload shape.",
    },
    503: {
        "model": ServiceUnavailable503,
        "description": (
            "The gateway could not reach an upstream tier, or secondary analysis was required "
            "but not configured on this deployment."
        ),
    },
}

_DEFAULT_RULE_ENGINE_URL = "http://127.0.0.1:8778"


def _rule_engine_base_url() -> str:
    return os.environ.get("RULE_ENGINE_URL", _DEFAULT_RULE_ENGINE_URL).rstrip("/")


def _shadow_agent_base_url() -> str:
    return os.environ.get("SHADOW_AGENT_URL", "").strip().rstrip("/")


def _shadow_api_key() -> str | None:
    raw = os.environ.get("SHADOW_API_KEY", "").strip()
    return raw or None


_DEFAULT_SHADOW_ANALYZE_TIMEOUT_S = 3.0


def _shadow_analyze_timeout_seconds(override: float | None) -> float:
    """Hard deadline for ``POST …/v1/analyze``; on expiry orchestrator returns a ``FLAG`` fallback."""
    if override is not None:
        return max(0.05, float(override))
    raw = os.environ.get("ORCHESTRATOR_SHADOW_ANALYZE_TIMEOUT_SECONDS", "").strip()
    if raw:
        return max(0.05, float(raw))
    return _DEFAULT_SHADOW_ANALYZE_TIMEOUT_S


def create_app(
    *,
    rule_engine_url: str | None = None,
    shadow_agent_url: str | None = None,
    shadow_api_key: str | None = None,
    shadow_analyze_timeout_seconds: float | None = None,
    audit_database_url: str | None = None,
    graph_client_override: GraphClient | None = None,
    analytics_provider: AnalyticsProvider | None = None,
    duck_analytics_provider: AnalyticsProvider | None = None,
    anumana_redis_client: Any | None = None,
    shadow_dispatch_nats_client: Any | None = None,
    compliance_export_hmac_key: str | bytes | None = None,
    audit_background_poll: bool = True,
    ai_feedback_jsonl: str | os.PathLike[str] | None = None,
) -> FastAPI:
    """
    Build the ASGI app.

    Parameters:
        rule_engine_url: Override rule engine base URL (tests).
        shadow_agent_url: Override Shadow sidecar base URL (tests); falls back to :envvar:`SHADOW_AGENT_URL`.
        shadow_api_key: Override ``X-Shadow-Token`` (tests); falls back to :envvar:`SHADOW_API_KEY`.
        shadow_analyze_timeout_seconds: Override Shadow ``/v1/analyze`` read deadline (tests);
            falls back to :envvar:`ORCHESTRATOR_SHADOW_ANALYZE_TIMEOUT_SECONDS` or **3s**.
        audit_database_url: Async SQLAlchemy URL for audit/case persistence (tests). When ``None``,
            uses :envvar:`ORCHESTRATOR_AUDIT_DATABASE_URL` then :envvar:`SHADOW_DATABASE_URL`.
        graph_client_override: Optional fixed :class:`~orchestrator.graph.client.GraphClient` for tests;
            when ``None``, a client is chosen from graph-related environment variables (or a no-op).
        analytics_provider: Optional :class:`~orchestrator.analytics.provider.AnalyticsProvider` (tests).
            When ``None``, :func:`~orchestrator.analytics.factory.build_analytics_provider` selects the backend
            from :envvar:`ENVIRONMENT` (**LocalAnalytics** / DuckDB locally, **CloudAnalytics** / ClickHouse in cloud).
        duck_analytics_provider: Deprecated alias for ``analytics_provider``.
        anumana_redis_client: Optional injected async Redis client for ``POST /ingest`` tests; when ``None``,
            uses :envvar:`ANUMANA_REDIS_URL` if set.
        shadow_dispatch_nats_client: Optional NATS client for ``shadow.investigate`` publishes (tests);
            when ``None`` and :envvar:`NATS_URL` is set, the app connects on startup.
        compliance_export_hmac_key: Optional secret for HMAC-SHA256 over the compliance ZIP ``manifest.json``;
            when ``None``, uses :envvar:`ORCHESTRATOR_COMPLIANCE_EXPORT_HMAC_KEY` (empty disables signing output).
        audit_background_poll: When ``True`` (default), starts the audit ``process_new_audit_logs`` poll loop;
            set ``False`` in tests that use SQLite ``:memory:`` plus their own async sessions to avoid lock races.
        ai_feedback_jsonl: Optional override path for ``POST /v1/ai/feedback`` JSONL sink (tests); when ``None``,
            uses :envvar:`ORCHESTRATOR_AI_FEEDBACK_JSONL` or ``{cwd}/data/ai_rejection_feedback.jsonl``.
    """
    rule_base = (rule_engine_url or _rule_engine_base_url()).rstrip("/")
    shadow_base = (
        shadow_agent_url if shadow_agent_url is not None else _shadow_agent_base_url()
    ).rstrip("/")
    shadow_key = shadow_api_key if shadow_api_key is not None else _shadow_api_key()
    shadow_deadline_s = _shadow_analyze_timeout_seconds(shadow_analyze_timeout_seconds)

    if audit_database_url is None:
        audit_url = resolve_audit_database_url()
    else:
        audit_url = audit_database_url.strip() or None

    graph_client_injected = graph_client_override
    analytics_injected = analytics_provider or duck_analytics_provider
    anumana_redis_injected = anumana_redis_client
    shadow_dispatch_nats_injected = shadow_dispatch_nats_client
    compliance_hmac_injected = compliance_export_hmac_key
    audit_poll_injected = audit_background_poll

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.audit_engine = None
        app.state.audit_session_factory = None
        app.state.audit_poll_task = None
        app.state.graph_client = (
            graph_client_injected
            if graph_client_injected is not None
            else graph_client_from_environment()
        )
        if analytics_injected is not None:
            app.state.analytics = analytics_injected
        else:
            app.state.analytics = build_analytics_provider()
        app.state.anumana_ingest_secret = (
            os.environ.get("ANUMANA_TELEMETRY_INGEST_KEY") or ""
        ).strip() or None
        app.state.anumana_redis_key = (
            os.environ.get("ANUMANA_TELEMETRY_REDIS_KEY") or "anumana:browser_telemetry"
        ).strip()
        if anumana_redis_injected is not None:
            app.state.anumana_redis = anumana_redis_injected
        else:
            aru = (os.environ.get("ANUMANA_REDIS_URL") or "").strip()
            if aru:
                import redis.asyncio as redis_mod

                app.state.anumana_redis = redis_mod.from_url(aru, decode_responses=False)
            else:
                app.state.anumana_redis = None
        app.state.shadow_dispatch_nats = None
        shadow_dispatch_nc: Any = shadow_dispatch_nats_injected
        if shadow_dispatch_nc is None:
            nats_url = (os.environ.get("NATS_URL") or "").strip()
            if nats_url:
                try:
                    import nats  # noqa: PLC0415 — ``pip install tarka-orchestrator[worker]``

                    shadow_dispatch_nc = await nats.connect(nats_url)
                except Exception:
                    logger.exception("orchestrator_shadow_dispatch_nats_connect_failed")
                    shadow_dispatch_nc = None
        app.state.shadow_dispatch_nats = shadow_dispatch_nc
        if compliance_hmac_injected is not None:
            if isinstance(compliance_hmac_injected, bytes):
                app.state.compliance_export_hmac_key = compliance_hmac_injected
            else:
                app.state.compliance_export_hmac_key = str(compliance_hmac_injected).strip().encode("utf-8")
        else:
            app.state.compliance_export_hmac_key = (
                (os.environ.get("ORCHESTRATOR_COMPLIANCE_EXPORT_HMAC_KEY") or "").strip().encode("utf-8")
            )
        engine = None
        task: asyncio.Task | None = None
        stop: asyncio.Event | None = None
        if audit_url:
            import tarka_shared.audit_trail  # noqa: F401, PLC0415
            import tarka_shared.engine_rules  # noqa: F401, PLC0415
            import tarka_shared.fraud_rules  # noqa: F401, PLC0415

            import orchestrator.models.cases  # noqa: F401, PLC0415
            import orchestrator.models.decision  # noqa: F401, PLC0415

            engine = build_audit_engine(audit_url)
            fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            app.state.audit_engine = engine
            app.state.audit_session_factory = fac
            if audit_poll_injected:
                stop = asyncio.Event()

                async def _poll_loop() -> None:
                    assert fac is not None
                    assert stop is not None
                    while not stop.is_set():
                        try:
                            async with fac() as session:
                                async with session.begin():
                                    await process_new_audit_logs(session)
                        except Exception:
                            logger.exception("orchestrator_audit_poll_batch_failed")
                        if stop.is_set():
                            break
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=5.0)
                        except TimeoutError:
                            pass

                task = asyncio.create_task(_poll_loop(), name="orchestrator-audit-poll")
            app.state.audit_poll_task = task
        yield
        if stop is not None:
            stop.set()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if engine is not None:
            await engine.dispose()
        sdn = getattr(app.state, "shadow_dispatch_nats", None)
        if sdn is not None and shadow_dispatch_nats_injected is None:
            try:
                await sdn.drain()
                await sdn.close()
            except Exception:
                logger.exception("orchestrator_shadow_dispatch_nats_close_failed")
        ar = getattr(app.state, "anumana_redis", None)
        if ar is not None and anumana_redis_injected is None:
            try:
                await ar.aclose()
            except Exception:
                logger.exception("orchestrator_anumana_redis_close_failed")
        dprov = getattr(app.state, "analytics", None)
        if dprov is not None:
            try:
                dprov.close()
            except Exception:
                logger.exception("orchestrator_analytics_close_failed")
        gc = getattr(app.state, "graph_client", None)
        if gc is not None:
            try:
                await gc.close()
            except Exception:
                logger.exception("orchestrator_graph_client_close_failed")

    application = FastAPI(
        title="Tarka Orchestrator API",
        description=_ORCHESTRATOR_DESCRIPTION,
        version="0.1.0",
        docs_url=None,
        redoc_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=_ORCHESTRATOR_TAGS,
        lifespan=lifespan,
    )
    application.state.rule_engine_url = rule_base
    application.state.shadow_agent_url = shadow_base or None
    application.state.shadow_api_key = shadow_key
    application.state.shadow_analyze_timeout_seconds = shadow_deadline_s
    application.state.ai_feedback_jsonl_path = resolve_ai_feedback_jsonl_path(ai_feedback_jsonl)

    @application.exception_handler(RequestValidationError)
    async def _ingest_validation_fail_closed(request: Request, exc: RequestValidationError):
        """Map ``/ingest`` body failures to **400** fail-closed (other routes keep FastAPI **422**)."""
        if request.scope.get("path", "").rstrip("/") == "/ingest":
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_ingestion_payload",
                    "detail": jsonable_encoder(exc.errors()),
                },
            )
        return await request_validation_exception_handler(request, exc)

    @application.post(
        "/ingest",
        tags=["Anumana"],
        summary="Browser SDK telemetry → Redis (hot path)",
        description=(
            "Accepts **canvas_fingerprint** / **canvas_raster_digest_hex** and optional **ip** hint plus "
            "optional sealed **telemetry_packet**. Body must satisfy strict **IngestionSchema** "
            "(unknown keys rejected); validation failures return **400**. One **async Redis pipeline** per "
            "request: **LPUSH** JSON "
            "to the telemetry stream key and **INCR**/**EXPIRE** fixed-window velocity counters for "
            "**device** (SHA-256 of canvas string) and **IP** (ingress ``X-Forwarded-For`` first hop + "
            "optional JSON ``ip``) at **1m**, **5m**, and **1h** buckets (prefix ``ANUMANA_VELOCITY_KEY_PREFIX``). "
            "No graph upsert, no DuckDB append. Optional auth: ``ANUMANA_TELEMETRY_INGEST_KEY`` + "
            "``X-Anumana-Ingest-Key``. CORS: ``ANUMANA_TELEMETRY_CORS_ORIGINS`` (default ``*``)."
        ),
    )
    async def anumana_browser_telemetry_ingest(
        request: Request,
        body: IngestionSchema,
    ) -> dict[str, Any]:
        return await handle_browser_telemetry_ingest(
            request,
            body,
            redis_client=getattr(request.app.state, "anumana_redis", None),
            redis_key=str(getattr(request.app.state, "anumana_redis_key", "anumana:browser_telemetry")),
            ingest_secret=getattr(request.app.state, "anumana_ingest_secret", None),
        )

    @application.post(
        "/v1/ingest",
        tags=["Ingestion"],
        summary="Ingest a transaction",
        description=(
            "Accepts a **TransactionSchema** JSON body. The orchestrator evaluates policy first; "
            "if the outcome requests secondary fraud review, it may run an additional analysis step "
            "and merge that structured result. Pure allow/block/flag outcomes do not trigger that "
            "extra step. After a successful policy response, graph upsert (JanusGraph / Neo4j) and "
            "DuckDB append run concurrently via ``asyncio.gather``; for non-Shadow outcomes they are "
            "scheduled as **background tasks** so slow storage does not delay the HTTP response."
        ),
        response_model=IngestResponse,
        responses=_RESP_INGEST,
        response_model_exclude_none=True,
    )
    async def v1_ingest(
        transaction: TransactionSchema,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Evaluate policy for the given transaction envelope and optionally attach analysis output."""
        return await execute_transaction_ingest(
            request=request,
            background_tasks=background_tasks,
            transaction=transaction,
        )

    @application.post(
        "/v1/ingest/chargeback",
        tags=["Ingestion"],
        summary="Ingest a chargeback (TYPE: CHARGEBACK)",
        description=(
            "Creates a **new** dispute transaction (fresh ``entity_id``) with ``metadata.ingestion_type=CHARGEBACK``, "
            "auto-linking ``metadata.session_id`` / ``linked_session_id`` to the original payment when a "
            "``session_id`` is supplied or can be resolved from ``audit_logs``. Policy evaluation matches "
            "``POST /v1/ingest``; lifecycle rows receive a **Dispute** tag for dashboard surfacing."
        ),
        response_model=IngestResponse,
        responses=_RESP_INGEST,
        response_model_exclude_none=True,
    )
    async def v1_ingest_chargeback(
        body: ChargebackIngestRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        fac = getattr(request.app.state, "audit_session_factory", None)
        resolved = (body.session_id or "").strip() or None
        try:
            if fac is not None and not resolved:
                async with fac() as session:
                    resolved = await resolve_linked_session_id(session, str(body.original_entity_id))
        except Exception:
            logger.exception("chargeback_session_resolve_failed")
        txn = build_chargeback_transaction(
            original_entity_id=body.original_entity_id,
            amount=body.amount,
            country=body.country,
            metadata=dict(body.metadata),
            linked_session_id=resolved,
        )
        return await execute_transaction_ingest(
            request=request,
            background_tasks=background_tasks,
            transaction=txn,
        )

    @application.post(
        "/v1/investigation/prime",
        tags=["Investigation"],
        summary="Prime Shadow review from an uploaded document",
        description=(
            "Accepts a single **.pdf** or **.txt** upload, extracts plaintext (PDF via embedded text; "
            "no heavy OCR), scans for order-like, passport-like, and transaction-like identifiers, "
            "returns a ready-to-send Shadow prompt when any IDs are found, and (when configured) "
            "a per-ID **knowledge** bundle: graph-linked users, **2-hop neighbor networks** (JanusGraph / Neo4j), "
            "**DuckDB cluster spend velocity** (30d window), active lifecycle investigation counts, "
            "and ``PENDING_ACTION`` conflict flags. When ``SHADOW_AGENT_URL`` is set, the orchestrator also "
            "calls ``POST …/v1/analyze`` with that topology + velocity in ``graph_context`` so Shadow can emit "
            "a **Cluster Analysis** narrative."
        ),
        response_model=InvestigationPrimeResponse,
        responses={
            400: {"description": "Unsupported extension or empty upload."},
            422: {
                "model": HTTPValidationError422,
                "description": "Multipart form did not include a file part.",
            },
            503: {
                "model": ServiceUnavailable503,
                "description": "PDF parsing dependency missing or misconfigured.",
            },
        },
    )
    async def v1_investigation_prime(
        request: Request,
        file: UploadFile = File(
            ...,
            description="One `.pdf` or `.txt` file dropped by the analyst.",
        ),
    ) -> dict[str, Any]:
        raw_name = (file.filename or "upload").strip() or "upload"
        # Flatten path-like names from clients.
        filename = raw_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        lower = filename.lower()
        if not (lower.endswith(".pdf") or lower.endswith(".txt")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "unsupported_file_type", "filename": filename},
            )
        try:
            data = await file.read()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "upload_read_failed", "message": str(exc)},
            ) from exc
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "empty_upload", "filename": filename},
            )
        try:
            ids, prompt = prime_from_upload(filename=filename, data=data)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "unsupported_file_type", "message": str(exc)},
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "pdf_parser_unavailable", "message": str(exc)},
            ) from exc
        gc: GraphClient = request.app.state.graph_client
        analytics = get_analytics(request)
        fac = getattr(request.app.state, "audit_session_factory", None)
        knowledge_raw: list[dict[str, Any]] = []
        if ids:
            if fac is not None:
                async with fac() as session:
                    knowledge_raw = await knowledge_bundle_for_detected_ids(
                        ids,
                        graph_client=gc,
                        session=session,
                        analytics=analytics,
                    )
            else:
                knowledge_raw = await knowledge_bundle_for_detected_ids(
                    ids,
                    graph_client=gc,
                    session=None,
                    analytics=analytics,
                )

        cluster_analysis: dict[str, Any] | None = None
        shadow_base = getattr(request.app.state, "shadow_agent_url", None)
        shadow_key = getattr(request.app.state, "shadow_api_key", None)
        if ids and shadow_base:
            read_s = float(request.app.state.shadow_analyze_timeout_seconds)
            shadow_http_timeout = httpx.Timeout(read_s, connect=min(5.0, read_s))
            anchor = ids[0]
            try:
                gctx = await build_prime_shadow_graph_context(
                    anchor_id=anchor,
                    graph_client=gc,
                    analytics=analytics,
                )
                tx_payload = synthetic_dispute_transaction(anchor_id=anchor, filename=filename)
                tx_model = TransactionSchema.model_validate(tx_payload)
                body: dict[str, Any] = {
                    "transaction": tx_model.model_dump(mode="json"),
                    "graph_context": gctx,
                }
                headers: dict[str, str] = {}
                if shadow_key:
                    headers["X-Shadow-Token"] = shadow_key
                async with httpx.AsyncClient(timeout=shadow_http_timeout) as client:
                    r = await client.post(
                        f"{str(shadow_base).rstrip('/')}/v1/analyze",
                        json=body,
                        headers=headers or None,
                    )
                    r.raise_for_status()
                    cluster_analysis = r.json()
            except Exception:
                logger.exception(
                    "orchestrator_prime_shadow_cluster_failed anchor=%s filename=%s",
                    anchor,
                    filename,
                )
                cluster_analysis = None

        return {
            "filename": filename,
            "detected_ids": ids,
            "prime_prompt": prompt,
            "knowledge": knowledge_raw,
            "cluster_analysis": cluster_analysis,
        }

    @application.post(
        "/v1/rules/shadow-test",
        tags=["Rules"],
        summary="Shadow-test a hypothetical rule against recent traffic",
        description=(
            "Replays the provided ``root_node`` predicate against up to **1,000** recent "
            "``audit_logs`` transaction snapshots (newest first). When no audit history exists, "
            "a deterministic synthetic cohort is used so local demos still surface high-hit-rate "
            "warnings. Intended **before** persisting a new rule to ``engine_rules``."
        ),
        response_model=RuleShadowTestResponse,
        responses={
            422: {
                "model": HTTPValidationError422,
                "description": "Invalid logical AST, unknown action, or empty cohort.",
            },
            503: {
                "model": ServiceUnavailable503,
                "description": "Rule-engine evaluator dependency is not installed in this process.",
            },
        },
    )
    async def v1_rules_shadow_test(
        request: Request,
        body: RuleShadowTestRequest,
    ) -> RuleShadowTestResponse:
        """Estimate how aggressively a draft rule would have fired on recent production-shaped rows."""
        fac = getattr(request.app.state, "audit_session_factory", None)
        try:
            payload = await execute_rule_shadow_test(
                fac,
                root_payload=body.root_node,
                action_value=body.action.strip().upper(),
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "shadow_test_invalid_ast", "errors": exc.errors()},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "shadow_test_invalid_input", "message": str(exc)},
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "rule_engine_unavailable", "message": str(exc)},
            ) from exc
        return RuleShadowTestResponse.model_validate(payload)

    @application.get(
        "/v1/marketplace/users/{user_id}/entity-profile",
        tags=["Marketplace"],
        summary="Entity Explorer unified profile",
        description=(
            "Assembles **Postgres** lifecycle case status (``lifecycle_cases`` / ``user_link_key``), a "
            "**JanusGraph or Neo4j** ≤2-hop neighborhood (devices + IPs), **analytics plane** marketplace metrics "
            "(spend, distinct listings, promo success rate), and—when ``SHADOW_AGENT_URL`` is set and "
            "``ORCHESTRATOR_ENTITY_PROFILE_SKIP_SHADOW`` is not truthy—a live **Shadow** ``/v1/analyze`` "
            "executive summary seeded with the same graph + Duck context."
        ),
        response_model=EntityProfileResponse,
        responses={
            422: {
                "model": HTTPValidationError422,
                "description": "Invalid or empty ``user_id`` path parameter.",
            },
        },
    )
    async def v1_marketplace_user_entity_profile(
        request: Request,
        user_id: str,
    ) -> EntityProfileResponse:
        uid = (user_id or "").strip()
        if not uid or len(uid) > 512 or "\x00" in uid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_user_id", "message": "user_id must be non-empty and ≤512 chars"},
            )
        gc: GraphClient = request.app.state.graph_client
        analytics = get_analytics(request)
        fac = getattr(request.app.state, "audit_session_factory", None)
        shadow_base = getattr(request.app.state, "shadow_agent_url", None)
        shadow_key = getattr(request.app.state, "shadow_api_key", None)
        shadow_deadline = float(getattr(request.app.state, "shadow_analyze_timeout_seconds", 15.0))
        try:
            payload = await build_entity_profile_payload(
                user_id=uid,
                audit_session_factory=fac,
                graph_client=gc,
                analytics=analytics,
                shadow_base=shadow_base,
                shadow_key=shadow_key,
                shadow_timeout_s=shadow_deadline,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_user_id", "message": str(exc)},
            ) from exc
        return EntityProfileResponse.model_validate(payload)

    @application.put(
        "/v1/cases/{case_id}/status",
        tags=["Cases"],
        summary="Update lifecycle case status",
        description=(
            "Requires ``X-Auth-Token`` and a JSON body with ``status`` plus ``reason_code``. "
            "Validates the lifecycle state machine and appends an audit row to ``case_history`` "
            "(``audit_log_id`` null; ``from_status`` / ``to_status`` / ``reason_code`` / token fingerprint)."
        ),
        response_model=CaseStatusUpdateResponse,
        responses={
            404: {"description": "Unknown ``lifecycle_cases.case_id``."},
            409: {"description": "Illegal state transition or corrupt stored status."},
            422: {"model": HTTPValidationError422, "description": "Missing token, reason, or invalid status."},
            503: {"model": ServiceUnavailable503, "description": "Audit database not configured."},
        },
    )
    async def v1_put_case_status(
        request: Request,
        case_id: str,
        body: CaseStatusUpdateRequest,
        x_auth_token: Annotated[str, Header(alias="X-Auth-Token")],
    ) -> CaseStatusUpdateResponse:
        tok = (x_auth_token or "").strip()
        if not tok:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "missing_auth_token",
                    "message": "X-Auth-Token header is required and must be non-empty",
                },
            )
        fac = getattr(request.app.state, "audit_session_factory", None)
        gc: GraphClient = request.app.state.graph_client
        payload = await put_lifecycle_case_status(
            audit_session_factory=fac,
            case_id=case_id,
            new_status_raw=body.status,
            reason_code=body.reason_code,
            auth_token=tok,
            graph_client=gc,
        )
        return CaseStatusUpdateResponse.model_validate(payload)

    @application.get(
        "/v1/cases/{case_id}/export",
        tags=["Cases"],
        summary="Compliance export (signed ZIP)",
        description=(
            "Returns ``application/zip`` bundling ``case.json`` (lifecycle + Shadow ``cases`` row), "
            "``graph_snapshot.json`` (evidence locker snapshot), and ``rust_trace.json`` (latest ``decisions`` "
            "execution trace for the case entity). Includes ``manifest.json`` (SHA-256 of those files) and "
            "``signature.txt`` (HMAC-SHA256 of the manifest when a signing key is configured). "
            "Requires the same ``X-Auth-Token`` convention as ``PUT /v1/cases/{case_id}/status``."
        ),
        response_class=Response,
        responses={
            404: {"description": "Unknown ``lifecycle_cases.case_id``."},
            422: {"model": HTTPValidationError422, "description": "Missing token or invalid ``case_id``."},
            503: {"model": ServiceUnavailable503, "description": "Audit database not configured."},
        },
    )
    async def v1_export_case_compliance(
        request: Request,
        case_id: str,
        x_auth_token: Annotated[str, Header(alias="X-Auth-Token")],
    ) -> Response:
        tok = (x_auth_token or "").strip()
        if not tok:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "missing_auth_token",
                    "message": "X-Auth-Token header is required and must be non-empty",
                },
            )
        fac = getattr(request.app.state, "audit_session_factory", None)
        if fac is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "audit_database_unconfigured",
                    "message": "Case export requires ORCHESTRATOR_AUDIT_DATABASE_URL (or test override).",
                },
            )
        hmac_key = getattr(request.app.state, "compliance_export_hmac_key", b"") or b""
        try:
            body = await build_compliance_export_zip(
                audit_session_factory=fac,
                case_id=case_id,
                hmac_key=hmac_key,
            )
        except CaseExportNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "case_not_found", "message": (case_id or "").strip()},
            ) from None
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_case_id", "message": str(exc)},
            ) from exc

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (case_id or "").strip())[:72] or "case"
        fname = f"case-{safe}-compliance-export.zip"
        return Response(
            content=body,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @application.post(
        "/v1/cases/{case_id}/file-dispute",
        tags=["Cases"],
        summary="File dispute: lock case and export evidence PDF",
        description=(
            "Transitions the lifecycle case to ``PENDING_ACTION`` with ``reason_code`` "
            f"``{FILE_DISPUTE_LOCK_REASON}`` (dispute lock), then returns ``application/pdf`` bundling "
            "case JSON, shadow graph snapshot, rule-engine trace, and a two-hop graph diagram "
            f"(section title: *{PDF_GRAPH_SECTION_TITLE}*). Requires ``X-Auth-Token``."
        ),
        response_class=Response,
        responses={
            404: {"description": "Unknown ``lifecycle_cases.case_id``."},
            409: {"description": "Illegal state transition or corrupt stored status."},
            422: {"model": HTTPValidationError422, "description": "Missing token or invalid ``case_id``."},
            503: {"model": ServiceUnavailable503, "description": "Audit database not configured."},
        },
    )
    async def v1_file_dispute_lock_export_pdf(
        request: Request,
        case_id: str,
        x_auth_token: Annotated[str, Header(alias="X-Auth-Token")],
    ) -> Response:
        tok = (x_auth_token or "").strip()
        if not tok:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "missing_auth_token",
                    "message": "X-Auth-Token header is required and must be non-empty",
                },
            )
        fac = getattr(request.app.state, "audit_session_factory", None)
        if fac is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "audit_database_unconfigured",
                    "message": "File dispute export requires ORCHESTRATOR_AUDIT_DATABASE_URL (or test override).",
                },
            )
        gc: GraphClient = request.app.state.graph_client
        await put_lifecycle_case_status(
            audit_session_factory=fac,
            case_id=case_id,
            new_status_raw=CaseStatus.PENDING_ACTION.value,
            reason_code=FILE_DISPUTE_LOCK_REASON,
            auth_token=tok,
            graph_client=gc,
        )
        try:
            pdf_body = await build_dispute_evidence_pdf_for_case(
                audit_session_factory=fac,
                case_id=case_id,
                graph_client=gc,
            )
        except CaseExportNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "case_not_found", "message": (case_id or "").strip()},
            ) from None
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_case_id", "message": str(exc)},
            ) from exc

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (case_id or "").strip())[:72] or "case"
        fname = f"case-{safe}-dispute-evidence.pdf"
        return Response(
            content=pdf_body,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @application.get(
        "/v1/analytics/velocity",
        tags=["Analytics"],
        summary="Transactions per minute by country",
        description=(
            "Runs the analytics-plane velocity rollup (local: DuckDB ``v_analytics_transactions``; cloud: "
            "ClickHouse ``orchestrator_analytics_ingested``). Uses minute bucket × country. "
            "The query executes in a worker thread so slow async work does not block the event loop."
        ),
        response_model=AnalyticsVelocityResponse,
        responses={
            503: {
                "model": ServiceUnavailable503,
                "description": "Analytics provider is not attached to this app instance.",
            },
        },
    )
    async def v1_analytics_velocity(
        _request: Request,
        analytics: Annotated[AnalyticsProvider | None, Depends(get_analytics)],
    ) -> AnalyticsVelocityResponse:
        """Minute-level transaction velocity grouped by country (analytics plane)."""
        if analytics is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "analytics_unavailable",
                    "message": "Analytics provider is not configured on this process.",
                },
            )

        def _run() -> tuple[list[dict[str, Any]], float]:
            return analytics.transactions_per_minute_by_country_timed()

        rows_raw, ms = await asyncio.to_thread(_run)
        rows = [
            AnalyticsVelocityRow(
                minute_bucket=str(r["minute_bucket"]),
                country=str(r["country"]),
                txn_count=int(r["txn_count"]),
            )
            for r in rows_raw
        ]
        return AnalyticsVelocityResponse(rows=rows, query_ms=round(ms, 4))

    @application.get(
        "/v1/analytics/transactions",
        tags=["Analytics"],
        summary="Unified analytical transaction stream",
        description=(
            "Returns recent analytical transaction rows (newest ``ts`` first): local DuckDB unified view "
            "or cloud ClickHouse ``orchestrator_analytics_ingested``."
        ),
        response_model=AnalyticsTransactionsSnapshot,
        responses={
            503: {
                "model": ServiceUnavailable503,
                "description": "Analytics provider is not attached to this process.",
            },
        },
    )
    async def v1_analytics_transactions(
        _request: Request,
        analytics: Annotated[AnalyticsProvider | None, Depends(get_analytics)],
        limit: int = Query(
            500,
            ge=1,
            le=10_000,
            description="Maximum rows to return (newest ``ts`` first).",
        ),
    ) -> AnalyticsTransactionsSnapshot:
        """Expose the analytical stream backing ingest append + seed data."""
        if analytics is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "analytics_unavailable",
                    "message": "Analytics provider is not configured on this process.",
                },
            )

        rows = await asyncio.to_thread(analytics.list_analytics_transactions, limit=limit)
        return AnalyticsTransactionsSnapshot(rows=rows)

    @application.get(
        "/health/full",
        tags=["Operations"],
        summary="Aggregate health matrix",
        description=(
            "Returns a single JSON snapshot with local process status and HTTP probes against "
            "configured upstream dependencies (policy tier health endpoint and analysis tier DB health "
            "when configured). Intended for load balancers and ops dashboards."
        ),
        response_model=HealthFullResponse,
    )
    async def health_full(request: Request) -> dict[str, Any]:
        """Aggregate readiness across this process and configured backends."""
        rule_base: str = request.app.state.rule_engine_url
        shadow_base: str | None = request.app.state.shadow_agent_url
        shadow_key: str | None = request.app.state.shadow_api_key
        timeout = httpx.Timeout(5.0, connect=3.0)

        services: list[dict[str, Any]] = [
            {
                "component": "orchestrator",
                "status": "ok",
                "latency_ms": 0.0,
                "detail": "process handling request",
            }
        ]

        async with httpx.AsyncClient(timeout=timeout) as client:
            t0 = time.perf_counter()
            try:
                r = await client.get(f"{rule_base}/health")
                dt_ms = (time.perf_counter() - t0) * 1000.0
                if r.status_code == 200:
                    services.append(
                        {
                            "component": "rule_engine",
                            "status": "ok",
                            "latency_ms": round(dt_ms, 2),
                            "detail": f"HTTP {r.status_code}",
                        }
                    )
                else:
                    services.append(
                        {
                            "component": "rule_engine",
                            "status": "degraded",
                            "latency_ms": round(dt_ms, 2),
                            "detail": f"HTTP {r.status_code}",
                        }
                    )
            except httpx.RequestError as exc:
                services.append(
                    {
                        "component": "rule_engine",
                        "status": "offline",
                        "latency_ms": None,
                        "detail": str(exc),
                    }
                )

            if not shadow_base:
                services.append(
                    {
                        "component": "shadow_agent",
                        "status": "not_configured",
                        "latency_ms": None,
                        "detail": "SHADOW_AGENT_URL unset on orchestrator",
                    }
                )
            else:
                headers: dict[str, str] = {}
                if shadow_key:
                    headers["X-Shadow-Token"] = shadow_key
                t1 = time.perf_counter()
                try:
                    r2 = await client.get(
                        f"{shadow_base}/health/db",
                        headers=headers or None,
                    )
                    dt2 = (time.perf_counter() - t1) * 1000.0
                    if r2.status_code == 200:
                        services.append(
                            {
                                "component": "shadow_agent",
                                "status": "ok",
                                "latency_ms": round(dt2, 2),
                                "detail": f"HTTP {r2.status_code}",
                            }
                        )
                    else:
                        services.append(
                            {
                                "component": "shadow_agent",
                                "status": "degraded",
                                "latency_ms": round(dt2, 2),
                                "detail": f"HTTP {r2.status_code}",
                            }
                        )
                except httpx.RequestError as exc:
                    services.append(
                        {
                            "component": "shadow_agent",
                            "status": "offline",
                            "latency_ms": None,
                            "detail": str(exc),
                        }
                    )

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "services": services,
        }

    @application.post(
        "/v1/demo/simulate_attack",
        tags=["Demo"],
        summary="Simulate attack-pattern batch (demo)",
        description=(
            "Returns a fixed batch of synthetic rows for UI demos (integrity scores and verdict labels). "
            "Does not persist data or call upstream tiers."
        ),
        response_model=DemoSimulateResponse,
        responses=_RESP_422,
    )
    async def v1_demo_simulate_attack() -> dict[str, Any]:
        """Return a non-streaming batch of simulated results for UI triggers."""
        n = 5
        now = datetime.now(UTC)
        results: list[dict[str, Any]] = []
        for i in range(n):
            tid = str(uuid.uuid4())
            results.append(
                {
                    "pattern_index": i,
                    "total": n,
                    "transaction_id": tid,
                    "amount": round(50.0 + i * 12.5, 2),
                    "currency": "USD",
                    "channel": "card_not_present",
                    "shadow_verdict": "FLAG" if i % 2 == 0 else "ALLOW",
                    "integrity_confidence": round(min(0.98, 0.52 + i * 0.09), 3),
                    "simulated_at": now.isoformat(),
                },
            )
        return {"total": n, "results": results}

    @application.post(
        "/v1/ai/feedback",
        tags=["AI"],
        summary="Record AI rejection feedback",
        description=(
            "Appends one JSON object per request to a local **JSONL** file (default under ``data/`` or "
            ":envvar:`ORCHESTRATOR_AI_FEEDBACK_JSONL`). Intended for analyst **rejection reasons** and "
            "downstream RAG / fine-tuning export pipelines. No database round-trip."
        ),
        response_model=AiFeedbackResponse,
        responses=_RESP_422,
        response_model_exclude_none=True,
    )
    async def v1_ai_feedback(
        body: AiFeedbackRequest,
        request: Request,
    ) -> dict[str, Any]:
        """Persist rejection reasons and optional correlation fields as one JSON line."""
        feedback_id = str(uuid.uuid4())
        received_at = datetime.now(UTC).isoformat()
        record: dict[str, Any] = {
            "schema": "tarka.ai_feedback.v1",
            "feedback_id": feedback_id,
            "received_at": received_at,
            "rejection_reasons": body.rejection_reasons,
        }
        if body.tenant_id is not None:
            record["tenant_id"] = body.tenant_id
        if body.trace_id is not None:
            record["trace_id"] = body.trace_id
        if body.entity_id is not None:
            record["entity_id"] = body.entity_id
        if body.source is not None:
            record["source"] = body.source
        if body.context is not None:
            record["context"] = body.context
        path: Path = getattr(request.app.state, "ai_feedback_jsonl_path")
        await asyncio.to_thread(append_feedback_jsonl, path, record)
        return {
            "ok": True,
            "feedback_id": feedback_id,
            "jsonl_path": str(path),
        }

    _cors_raw = (os.environ.get("ANUMANA_TELEMETRY_CORS_ORIGINS") or "*").strip()
    _cors_origins = ["*"] if _cors_raw == "*" else [o.strip() for o in _cors_raw.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["POST", "OPTIONS", "GET"],
        allow_headers=["*"],
    )

    return application


app = create_app()
