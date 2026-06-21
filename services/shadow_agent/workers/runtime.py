"""Shared bootstrap for Shadow NATS workers (DB + :class:`~shadow_agent.agent.ShadowAgent`)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from ingestor.schemas import TransactionSchema
from pydantic import ValidationError
from agent import ShadowAgent
from ai_gateway.base import AIGateway
from ai_gateway.factory import build_ai_gateway
from llm_client import OllamaLLMClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from tarka_shared.database.session import Base

logger = logging.getLogger(__name__)

_DEFAULT_ASYNC_DB_URL = "sqlite+aiosqlite:///:memory:"


@dataclass
class ShadowInvestigateRuntime:
    """Process-local resources for async ``shadow.investigate`` consumers."""

    gateway: AIGateway
    agent: ShadowAgent
    session_factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    llm_client: OllamaLLMClient

    async def evaluate_retroactive(
        self,
        manifest: dict[str, Any],
        context: dict[str, Any],
    ) -> list[str]:
        """
        Forensic taxonomy extraction: manifest evidence + operational context → ``category:value`` tags.

        Runs through the AI gateway inference wrapper (Ollama / vLLM) and returns a validated
        JSON array of structural tags (e.g. ``["vector:ato", "velocity:card_pool"]``).
        """
        from retroactive_label import evaluate_retroactive  # noqa: PLC0415

        async def _evaluate() -> list[str]:
            return await evaluate_retroactive(
                manifest,
                context,
                llm_client=self.llm_client,
            )

        tags = await self.gateway.run_shadow_investigate_inference(_evaluate)
        if not isinstance(tags, list):
            raise RuntimeError("evaluate_retroactive must return a list of tag strings")
        return tags


def transaction_from_investigate_payload(payload: dict[str, Any]) -> TransactionSchema | None:
    """
    Parse a NATS ``shadow.investigate`` body into :class:`~ingestor.schemas.TransactionSchema`.

    Requires a ``transaction`` object (orchestrator publishes this since v2 async handoff).
    Legacy payloads with only ``session_id`` + ``trace`` cannot be evaluated and return ``None``.
    """
    raw = payload.get("transaction")
    if not isinstance(raw, dict):
        return None
    try:
        return TransactionSchema.model_validate(raw)
    except ValidationError as exc:
        logger.warning(
            "shadow_investigate_invalid_transaction session_id=%s errors=%s",
            payload.get("session_id"),
            exc.errors(),
        )
        return None


def evaluation_trace_from_payload(payload: dict[str, Any]) -> list[Any]:
    trace = payload.get("trace")
    if isinstance(trace, list):
        return trace
    return []


async def bootstrap_shadow_investigate_runtime() -> ShadowInvestigateRuntime:
    """Initialize AI gateway, LLM client, audit DB, and :class:`~shadow_agent.agent.ShadowAgent`."""
    gateway = build_ai_gateway()
    llm = OllamaLLMClient(ai_gateway=gateway)
    agent = ShadowAgent(llm_client=llm)

    db_url = (os.environ.get("SHADOW_DATABASE_URL") or _DEFAULT_ASYNC_DB_URL).strip()
    engine_kw: dict[str, Any] = {"pool_pre_ping": True}
    if ":memory:" in db_url:
        engine_kw["poolclass"] = StaticPool
        engine_kw["connect_args"] = {"check_same_thread": False}

    engine: AsyncEngine = create_async_engine(db_url, **engine_kw)
    import tarka_shared.audit_trail  # noqa: F401, PLC0415 — register ORM mappers on ``Base``
    import tarka_shared.engine_rules  # noqa: F401
    import tarka_shared.fraud_rules  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    logger.info(
        "shadow_investigate_runtime_ready gateway=%s db_url=%s",
        type(gateway).__name__,
        db_url.split("@")[-1] if "@" in db_url else db_url,
    )
    return ShadowInvestigateRuntime(
        gateway=gateway,
        agent=agent,
        session_factory=session_factory,
        engine=engine,
        llm_client=llm,
    )


async def shutdown_shadow_investigate_runtime(runtime: ShadowInvestigateRuntime) -> None:
    """Release pooled HTTP and DB resources."""
    try:
        await runtime.llm_client.aclose()
    except Exception:
        logger.exception("shadow_investigate_runtime_llm_close_failed")
    await runtime.engine.dispose()
