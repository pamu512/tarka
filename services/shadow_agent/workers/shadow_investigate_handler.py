"""Shared ``shadow.investigate`` message handler (ShadowAgent evaluate + audit commit)."""

from __future__ import annotations

import logging
from typing import Any

from .runtime import (
    ShadowInvestigateRuntime,
    evaluation_trace_from_payload,
    transaction_from_investigate_payload,
)

logger = logging.getLogger(__name__)


async def handle_shadow_investigate_payload(
    runtime: ShadowInvestigateRuntime,
    payload: dict[str, Any],
) -> bool:
    """
    Run :meth:`~shadow_agent.agent.ShadowAgent.evaluate` for one decoded NATS payload.

    Returns ``True`` when evaluation completed and audit rows were committed; ``False`` when the
    payload could not be parsed into a transaction envelope (unrecoverable — caller should ``ack``).
    Raises on retryable engine / persistence failures for JetStream ``nak``.
    """
    tx = transaction_from_investigate_payload(payload)
    if tx is None:
        logger.warning(
            "shadow_investigate_skip_missing_transaction session_id=%s keys=%s",
            payload.get("session_id"),
            sorted(payload.keys()),
        )
        return False

    trace = evaluation_trace_from_payload(payload)
    graph_context: dict[str, Any] | None = {"evaluation_trace": trace} if trace else None
    entity_s = str(tx.entity_id)

    async def _evaluate() -> None:
        session = runtime.session_factory()
        try:
            decision, audit_log = await runtime.agent.evaluate(
                tx,
                session,
                graph_context=graph_context,
            )
            audit_id = getattr(audit_log, "id", None)
            if audit_id is None:
                raise RuntimeError(
                    f"shadow investigate audit commit missing audit_log.id entity_id={entity_s}",
                )
            logger.info(
                "shadow_investigate_evaluate_ok entity_id=%s risk_score=%s is_fraud=%s "
                "audit_log_id=%s session_id=%s",
                entity_s,
                decision.risk_score,
                decision.is_fraud,
                audit_id,
                payload.get("session_id"),
            )
        except Exception:
            logger.exception(
                "shadow_investigate_evaluate_failed entity_id=%s session_id=%s",
                entity_s,
                payload.get("session_id"),
            )
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()

    await runtime.gateway.run_shadow_investigate_inference(_evaluate)
    return True
