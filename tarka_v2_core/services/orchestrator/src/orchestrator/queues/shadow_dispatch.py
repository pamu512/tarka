"""Publish Shadow investigate jobs to NATS when policy yields a REVIEW outcome."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SHADOW_INVESTIGATE_SUBJECT = "shadow.investigate"


def shadow_investigate_subject() -> str:
    """NATS subject for Shadow handoff (override with ``SHADOW_DISPATCH_NATS_SUBJECT``)."""
    return (os.environ.get("SHADOW_DISPATCH_NATS_SUBJECT") or DEFAULT_SHADOW_INVESTIGATE_SUBJECT).strip()


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
) -> bool:
    """
    If this is a REVIEW decision and a NATS client is configured, publish JSON to ``shadow.investigate``.

    Payload: ``{"session_id": "<resolved>", "trace": <evaluation_trace list>}``.

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
    body = json.dumps(
        {"session_id": session_id, "trace": trace},
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    await nats_client.publish(subject, body)
    logger.info(
        "orchestrator_shadow_investigate_nats_published subject=%s session_id=%s entity_id=%s",
        subject,
        session_id,
        entity_id,
    )
    return True
