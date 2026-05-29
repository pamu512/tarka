"""Publish Shadow investigate jobs to NATS when policy yields a REVIEW outcome."""

from __future__ import annotations

import json
import logging
from typing import Any

from ingestor.manifest_schema import TransactionSchema

from orchestrator.config import get_settings

logger = logging.getLogger(__name__)


def shadow_investigate_subject() -> str:
    """NATS subject for Shadow handoff (override with ``SHADOW_DISPATCH_NATS_SUBJECT``)."""
    return get_settings().shadow_dispatch_nats_subject


def is_review_decision(rule_data: dict[str, Any], actions: list[str]) -> bool:
    """True when rule payload or actions indicate a fail-closed / manual REVIEW path."""
    if any(str(a).strip().upper() == "REVIEW" for a in actions):
        return True
    dec = rule_data.get("decision")
    return isinstance(dec, str) and dec.strip().upper() == "REVIEW"


def resolve_session_id(entity_id: str, metadata: dict[str, Any]) -> str:
    """Prefer explicit session id from metadata; otherwise fall back to transaction ``entity_id``."""
    for key in ("session_id", "sessionId", "anumana_session_id"):
        raw = metadata.get(key)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return entity_id


def evaluation_trace_from_rule_data(rule_data: dict[str, Any]) -> Any:
    trace = rule_data.get("evaluation_trace")
    if isinstance(trace, list):
        return trace
    return []


async def dispatch_shadow_investigate_if_review(
    nats_client: Any | None,
    *,
    entity_id: str,
    metadata: dict[str, Any],
    rule_data: dict[str, Any],
    actions: list[str],
    transaction: TransactionSchema | None = None,
) -> bool:
    """
    If this is a REVIEW decision and a NATS client is configured, publish JSON to ``shadow.investigate``.

    Payload::

        {
          "session_id": "<resolved>",
          "entity_id": "<transaction uuid>",
          "trace": <evaluation_trace list>,
          "transaction": { ... TransactionSchema ... }
        }

    The ``transaction`` envelope is required for the NATS worker to call
    :meth:`~shadow_agent.agent.ShadowAgent.evaluate` with full audit persistence.

    Returns ``True`` when a message was published.
    """
    if not is_review_decision(rule_data, actions):
        return False
    if nats_client is None:
        logger.debug(
            "orchestrator_shadow_investigate_nats_skipped_no_client entity_id=%s",
            entity_id,
        )
        return False

    session_id = resolve_session_id(entity_id, metadata)
    trace = evaluation_trace_from_rule_data(rule_data)
    subject = shadow_investigate_subject()
    body_obj: dict[str, Any] = {
        "session_id": session_id,
        "entity_id": entity_id,
        "trace": trace,
    }
    if transaction is not None:
        body_obj["transaction"] = transaction.model_dump(mode="json")
    body = json.dumps(
        body_obj,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    js = nats_client.jetstream() if hasattr(nats_client, "jetstream") else None
    if js is not None:
        from orchestrator.messaging.shadow_investigate_jetstream import (
            ensure_shadow_investigate_stream,
        )  # noqa: PLC0415

        await ensure_shadow_investigate_stream(js, subject=subject)
        await js.publish(subject, body)
    else:
        await nats_client.publish(subject, body)
    logger.info(
        "orchestrator_shadow_investigate_nats_published subject=%s session_id=%s entity_id=%s",
        subject,
        session_id,
        entity_id,
    )
    return True
