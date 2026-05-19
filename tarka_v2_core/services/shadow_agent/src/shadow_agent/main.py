"""FastAPI sidecar: forensic transaction analysis via :class:`~shadow_agent.agent.ShadowAgent`."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ingestor.schemas import TransactionSchema
from pydantic import ValidationError
from shadow_agent.agent import ShadowAgent, _ensure_case_for_shadow_audit
from shadow_agent.dispute_letter import RepresentmentLetterIn, generate_dispute_letter
from shadow_agent.graph_tool import find_linked_entities, neo4j_driver_from_env
from shadow_agent.review_integrity_tool import check_review_integrity
from shadow_agent.llm_client import OllamaLLMClient, ShadowLLMError
from shadow_agent.schemas import ShadowAnalyzeEnvelope
from shadow_agent.timeline import TimelineResponse, build_transaction_timeline
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.responses import Response
from tarka_shared.audit_trail import AuditLog
from tarka_shared.database.session import Base

logger = logging.getLogger(__name__)

_DEFAULT_ASYNC_DB_URL = "sqlite+aiosqlite:///:memory:"


def _chaos_latency_ms() -> int:
    """Milliseconds to sleep before ``/v1/analyze`` reaches the route (simulates slow LLM prep).

    Set ``CHAOS_LATENCY`` to a positive integer (e.g. ``5000``) to inject ``asyncio`` sleep for
    orchestrator timeout tests. ``0`` or unset disables the injector.
    """
    raw = os.environ.get("CHAOS_LATENCY", "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw, 10))
    except ValueError:
        logger.warning("CHAOS_LATENCY invalid %r — ignoring", raw)
        return 0


# Stable ``cases.id`` for ``audit_logs`` rows when the ingest payload has no usable ``entity_id``.
_SENTINEL_INGESTION_REJECT_CASE_ID = "00000000-0000-0000-0000-00000000d1ce"


def _support_id() -> str:
    return uuid.uuid4().hex[:12]


def _legacy_tarka_error_envelope(
    *,
    code: str,
    message: str,
    status_code: int,
    retryable: bool,
    support_id: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Match ``legacy_attic/services/shared/error_handlers._payload`` shape (Tarka API clients)."""
    return {
        "error": {
            "code": code,
            "message": message,
            "status_code": status_code,
            "retryable": retryable,
            "support_id": support_id,
            "details": details,
        }
    }


def _legacy_tarka_422_ingestion_payload(
    exc: RequestValidationError, support_id: str
) -> dict[str, Any]:
    return _legacy_tarka_error_envelope(
        code="request_validation_error",
        message="Transaction ingestion payload failed validation",
        status_code=422,
        retryable=False,
        support_id=support_id,
        details={"errors": exc.errors()},
    )


def _request_validation_raw_body(exc: RequestValidationError) -> str | None:
    raw = getattr(exc, "body", None)
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return repr(raw)
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, default=str, ensure_ascii=False)
    except TypeError:
        return str(raw)


def _ingestion_reject_audit_case_id(exc: RequestValidationError) -> str:
    """Prefer a valid ``entity_id`` from the raw JSON body; otherwise the sentinel ingestion case."""
    raw = getattr(exc, "body", None)
    if raw is None:
        return _SENTINEL_INGESTION_REJECT_CASE_ID
    try:
        if isinstance(raw, (bytes, bytearray)):
            data = json.loads(raw.decode("utf-8") or "{}")
        elif isinstance(raw, str):
            data = json.loads(raw or "{}")
        elif isinstance(raw, dict):
            data = raw
        else:
            return _SENTINEL_INGESTION_REJECT_CASE_ID
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return _SENTINEL_INGESTION_REJECT_CASE_ID
    eid = data.get("entity_id")
    if eid is None and isinstance(data.get("transaction"), dict):
        eid = data["transaction"].get("entity_id")
    if eid is None:
        return _SENTINEL_INGESTION_REJECT_CASE_ID
    try:
        UUID(str(eid))
    except ValueError:
        return _SENTINEL_INGESTION_REJECT_CASE_ID
    return str(eid)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an :class:`~sqlalchemy.ext.asyncio.AsyncSession` bound to the app engine.

    Uses the shared declarative :class:`~tarka_shared.database.session.Base` metadata registry.
    Callers (e.g. :meth:`~shadow_agent.agent.ShadowAgent.evaluate`) own ``commit()`` / transaction
    boundaries. This dependency only rolls back on unhandled errors and always closes in
    ``finally`` so pooled connections are not leaked.
    """
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state,
        "async_session_factory",
        None,
    )
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="async_session_factory_not_initialized",
        )

    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        try:
            if session.in_transaction():
                await session.rollback()
        except Exception as exc:
            logger.warning(
                "shadow_db_session_finalize_rollback_failed error=%s",
                exc,
                exc_info=True,
            )
        await session.close()


async def require_shadow_api_token(
    request: Request,
    x_shadow_token: Annotated[str | None, Header(alias="X-Shadow-Token")] = None,
) -> None:
    """Reject requests when ``X-Shadow-Token`` is missing or does not match ``SHADOW_API_KEY``."""
    expected = getattr(request.app.state, "shadow_api_key", None)
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="shadow_api_key_not_initialized",
        )
    if x_shadow_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    if len(x_shadow_token) != len(expected) or not secrets.compare_digest(x_shadow_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def get_shadow_agent(request: Request) -> ShadowAgent:
    """Resolve the process-wide :class:`~shadow_agent.agent.ShadowAgent` from application state."""
    agent = getattr(request.app.state, "shadow_agent", None)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="shadow_agent_not_initialized",
        )
    return agent


def build_app(
    *,
    shadow_agent: ShadowAgent | None = None,
    database_url: str | None = None,
    shadow_api_key: str | None = None,
) -> FastAPI:
    """
    Construct the ASGI application.

    Parameters:
        shadow_agent: Optional pre-built agent (e.g. ASGI tests with a stub LLM). When omitted,
            an :class:`~shadow_agent.llm_client.OllamaLLMClient` is created and closed on shutdown.
        database_url: Async SQLAlchemy URL (e.g. ``postgresql+asyncpg://...``). Defaults to
            ``SHADOW_DATABASE_URL`` or in-memory SQLite for local/tests.
        shadow_api_key: Optional API key (tests). When omitted, :envvar:`SHADOW_API_KEY` must be
            set and non-empty or startup **fails**.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        raw_key = shadow_api_key if shadow_api_key is not None else os.environ.get("SHADOW_API_KEY")
        if raw_key is None or not str(raw_key).strip():
            raise RuntimeError(
                "SHADOW_API_KEY is required but missing or empty; set a non-empty value in the "
                "environment before starting the shadow sidecar.",
            )
        app.state.shadow_api_key = str(raw_key).strip()

        owns_llm = False
        if shadow_agent is not None:
            app.state.shadow_agent = shadow_agent
        else:
            llm = OllamaLLMClient()
            app.state.shadow_agent = ShadowAgent(llm_client=llm)
            app.state._shadow_llm_client = llm
            owns_llm = True

        db_url = database_url or os.environ.get("SHADOW_DATABASE_URL", _DEFAULT_ASYNC_DB_URL)
        engine_kw: dict[str, Any] = {"pool_pre_ping": True}
        if ":memory:" in db_url:
            # One shared in-memory SQLite database for all pooled connections (default tests).
            engine_kw["poolclass"] = StaticPool
            engine_kw["connect_args"] = {"check_same_thread": False}
        engine: AsyncEngine = create_async_engine(db_url, **engine_kw)
        import tarka_shared.audit_trail  # noqa: F401, PLC0415 — register ORM mappers on ``Base``
        import tarka_shared.engine_rules  # noqa: F401 — ``engine_rules`` DDL with Shadow DB
        import tarka_shared.fraud_rules  # noqa: F401 — ``fraud_rules`` versioned rulesets

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        app.state.async_session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        fac = app.state.async_session_factory
        async with fac() as bootstrap:
            await _ensure_case_for_shadow_audit(bootstrap, _SENTINEL_INGESTION_REJECT_CASE_ID)
            await bootstrap.commit()
        app.state._db_engine = engine
        logger.info(
            "shadow_sidecar_startup owns_llm_client=%s db_backend=%s orm_tables=%s",
            owns_llm,
            engine.dialect.name,
            len(Base.metadata.tables),
        )
        yield
        if owns_llm:
            await app.state._shadow_llm_client.aclose()
        await engine.dispose()
        logger.info("shadow_sidecar_shutdown")

    application = FastAPI(
        title="tarka-shadow-agent",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.middleware("http")
    async def chaos_latency_injector(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Optional latency injection before ``POST /v1/analyze`` (see ``CHAOS_LATENCY``)."""
        path = request.url.path.rstrip("/") or "/"
        chaos_ms = _chaos_latency_ms()
        if chaos_ms > 0 and request.method.upper() == "POST" and path == "/v1/analyze":
            delay_s = chaos_ms / 1000.0
            logger.warning(
                "shadow_chaos_latency_injector path=%s delay_ms=%s",
                path,
                chaos_ms,
            )
            await asyncio.sleep(delay_s)
        return await call_next(request)

    @application.exception_handler(RequestValidationError)
    async def shadow_analyze_request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        path = request.url.path.rstrip("/") or "/"
        if path != "/v1/analyze" or request.method.upper() != "POST":
            return await request_validation_exception_handler(request, exc)

        support = _support_id()
        content = _legacy_tarka_422_ingestion_payload(exc, support)
        case_audit_id = _ingestion_reject_audit_case_id(exc)
        raw_body = _request_validation_raw_body(exc)
        errors_json = json.dumps(exc.errors(), ensure_ascii=False, default=str)

        logger.warning(
            "shadow_sidecar_rejected_ingestion case_id=%s support_id=%s errors=%s",
            case_audit_id,
            support,
            errors_json[:2048],
        )

        factory: async_sessionmaker[AsyncSession] | None = getattr(
            request.app.state,
            "async_session_factory",
            None,
        )
        if factory is None:
            logger.error(
                "shadow_rejected_ingestion_no_session_factory support_id=%s",
                support,
            )
            return JSONResponse(status_code=422, content=content)

        try:
            async with factory() as session:
                await _ensure_case_for_shadow_audit(session, case_audit_id)
                _code_cap = 32_768
                _notes_cap = 32_768
                code_ex = (raw_body or "")[:_code_cap]
                notes_ex = errors_json[:_notes_cap]
                session.add(
                    AuditLog(
                        case_id=case_audit_id,
                        action_taken="REJECTED_INGESTION",
                        code_executed=code_ex or None,
                        agent_notes=notes_ex or None,
                    ),
                )
                try:
                    await session.commit()
                except IntegrityError:
                    logger.critical(
                        "shadow_rejected_ingestion_audit_integrity_error case_id=%s support_id=%s",
                        case_audit_id,
                        support,
                        exc_info=True,
                    )
                    await session.rollback()
        except SQLAlchemyError:
            logger.critical(
                "shadow_rejected_ingestion_audit_db_error case_id=%s support_id=%s",
                case_audit_id,
                support,
                exc_info=True,
            )

        return JSONResponse(status_code=422, content=content)

    @application.get("/health/db")
    async def health_db(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, str]:
        await session.execute(text("SELECT 1"))
        await session.commit()
        return {"status": "ok"}

    @application.get(
        "/v1/transactions/{entity_id}/timeline",
        response_model=TimelineResponse,
    )
    async def get_transaction_timeline(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        entity_id: str,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> TimelineResponse:
        """Return all audit-linked events for this transaction plus cross-case device/IP matches."""
        try:
            UUID(entity_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_entity_id", "entity_id": entity_id},
            ) from exc
        try:
            out = await build_transaction_timeline(session, entity_id)
        except NotImplementedError as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail={"error": "timeline_unsupported_db", "message": str(exc)},
            ) from exc
        return out

    @application.post("/v1/tools/find-linked-entities")
    async def http_find_linked_entities(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
    ) -> JSONResponse:
        """Run ``find_linked_entities`` for a single transaction body (manual graph probe / ops)."""
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        try:
            if isinstance(raw.get("transaction"), dict):
                env = ShadowAnalyzeEnvelope.model_validate(raw)
                tx = env.transaction
            else:
                tx = TransactionSchema.model_validate(raw)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors(), body=raw) from exc

        drv = neo4j_driver_from_env()
        if drv is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "neo4j_not_configured"},
            )
        try:
            summary = await find_linked_entities(str(tx.entity_id), tx, drv)
        finally:
            await drv.close()
        return JSONResponse(
            content={"entity_id": str(tx.entity_id), "summary": summary},
        )

    @application.post("/v1/scout/coordinated-bursts")
    async def http_scout_coordinated_bursts(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
    ) -> JSONResponse:
        """DuckDB Scout: detect shared canvas_hash / webgl_vendor bursts (>5 acc_ids / 4h)."""
        from shadow_agent.scout_coordinated_burst import run_scout_coordinated_burst_probe

        payload = run_scout_coordinated_burst_probe()
        return JSONResponse(content=payload)

    @application.post("/v1/hypotheses/backtest-blocks")
    async def http_hypothesis_backtest_blocks(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
    ) -> JSONResponse:
        """Prompt 198: hourly production vs shadow block counts for visual backtest overlay."""
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        rule = raw.get("rule") or raw.get("suggested_rule")
        if not isinstance(rule, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "rule_required"},
            )
        try:
            from shadow_agent.hypothesis_backtest_client import (
                build_block_overlay_timeseries_for_rule,
            )

            duck_path = raw.get("duckdb_path")
            lookback = raw.get("lookback_days")
            series = build_block_overlay_timeseries_for_rule(
                rule,
                duckdb_path=str(duck_path).strip() if duck_path else None,
                lookback_days=int(lookback) if lookback is not None else None,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "backtest_blocks_unavailable", "message": str(exc)},
            ) from exc
        return JSONResponse(
            content={
                "lookback_days": lookback if lookback is not None else 7,
                "series": series,
            },
        )

    @application.post("/v1/hypotheses/validate-backtest")
    async def http_validate_hypothesis_backtest(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
    ) -> JSONResponse:
        """Prompt 196: DuckDB 7-day backtest gate (FPR must be < 0.1% for analyst suggestion)."""
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        rule = raw.get("rule") or raw.get("suggested_rule")
        if not isinstance(rule, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "rule_required"},
            )
        try:
            from shadow_agent.hypothesis_backtest_client import validate_suggested_rule_for_analyst

            duck_path = raw.get("duckdb_path")
            pg_url = raw.get("postgres_url")
            out = validate_suggested_rule_for_analyst(
                rule,
                duckdb_path=str(duck_path).strip() if duck_path else None,
                postgres_url=str(pg_url).strip() if pg_url else None,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "backtest_gate_unavailable", "message": str(exc)},
            ) from exc
        return JSONResponse(content=out)

    @application.post("/v1/saarthi/hypothesis-narrative")
    async def http_saarthi_hypothesis_narrative(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
    ) -> JSONResponse:
        """Saarthi (Gemini): two-sentence narrative for DuckDB Scout burst evidence."""
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        try:
            from saarthi.hypothesis_narrative import generate_hypothesis_narrative
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "saarthi_package_unavailable"},
            ) from exc
        scout_payload = (
            raw.get("scout_result") if isinstance(raw.get("scout_result"), dict) else raw
        )
        hypothesis_report = (
            raw.get("hypothesis_report") if isinstance(raw.get("hypothesis_report"), dict) else None
        )
        try:
            out = generate_hypothesis_narrative(
                scout_payload if isinstance(scout_payload, dict) else {},
                hypothesis_report=hypothesis_report,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_scout_payload", "message": str(exc)},
            ) from exc
        return JSONResponse(content=out)

    @application.post("/v1/tools/check-review-integrity")
    async def http_check_review_integrity(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
    ) -> JSONResponse:
        """Run ``check_review_integrity`` for ``listing_id`` (manual graph + optional DuckDB probe)."""
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        listing_id = raw.get("listing_id")
        if listing_id is None or not str(listing_id).strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "listing_id_required"},
            )

        drv = neo4j_driver_from_env()
        if drv is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "neo4j_not_configured"},
            )
        try:
            payload = await check_review_integrity(str(listing_id).strip(), drv)
        finally:
            await drv.close()
        return JSONResponse(content=payload)

    @application.post("/v1/tools/generate-dispute-letter")
    async def http_generate_dispute_letter(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
    ) -> JSONResponse:
        """Assemble a Markdown representment draft with IP, device hash, signature evidence, and event hash."""
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        try:
            evidence = RepresentmentLetterIn.model_validate(raw)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "representment_letter_validation", "errors": exc.errors()},
            ) from exc
        try:
            out = generate_dispute_letter(evidence)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "representment_letter_value_error", "message": str(exc)},
            ) from exc
        return JSONResponse(content=out.model_dump(mode="json"))

    @application.post("/v1/analyze")
    async def analyze_transaction(
        _auth: Annotated[None, Depends(require_shadow_api_token)],
        request: Request,
        agent: Annotated[ShadowAgent, Depends(get_shadow_agent)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> JSONResponse:
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_json", "message": str(exc)},
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "expected_json_object"},
            )
        try:
            if isinstance(raw.get("transaction"), dict):
                env = ShadowAnalyzeEnvelope.model_validate(raw)
                tx = env.transaction
                graph_ctx = env.graph_context
            else:
                tx = TransactionSchema.model_validate(raw)
                graph_ctx = None
        except ValidationError as exc:
            raise RequestValidationError(exc.errors(), body=raw) from exc

        logger.info(
            "shadow_sidecar_analyze_start entity_id=%s amount=%s graph_context=%s",
            tx.entity_id,
            tx.amount,
            graph_ctx is not None,
        )
        try:
            decision, audit_log = await agent.evaluate(tx, session, graph_context=graph_ctx)
        except ShadowLLMError as exc:
            logger.exception(
                "shadow_sidecar_analyze_shadow_llm_error entity_id=%s reason=%s",
                tx.entity_id,
                exc.reason,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "shadow_llm_error",
                    "reason": exc.reason,
                    "parse_attempts": exc.parse_attempts,
                },
            ) from exc
        except ValidationError as exc:
            logger.exception(
                "shadow_sidecar_analyze_validation_error entity_id=%s",
                tx.entity_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "shadow_decision_validation_failed", "errors": exc.errors()},
            ) from exc
        except Exception as exc:
            logger.exception(
                "shadow_sidecar_analyze_unhandled_error entity_id=%s",
                tx.entity_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="shadow_analyze_internal_error",
            ) from exc

        logger.info(
            "shadow_sidecar_analyze_ok entity_id=%s risk_score=%s is_fraud=%s",
            decision.transaction_id,
            decision.risk_score,
            decision.is_fraud,
        )
        code_ex = audit_log.code_executed or ""
        notes_ex = audit_log.agent_notes or ""
        _prompt_cap = 12_000
        _response_cap = 8_000
        payload: dict[str, Any] = {
            **decision.model_dump(mode="json"),
            "_debug": {
                "audit_log": repr(audit_log),
                "audit_log_id": getattr(audit_log, "id", None),
                "audit_log_snapshot": {
                    "transaction_id_correlation": audit_log.case_id,
                    "raw_llm_prompt_excerpt": code_ex[:_prompt_cap],
                    "raw_llm_response_excerpt": notes_ex[:_response_cap],
                    "is_fraud": decision.is_fraud,
                },
            },
        }
        return JSONResponse(content=payload)

    return application


app = build_app()
