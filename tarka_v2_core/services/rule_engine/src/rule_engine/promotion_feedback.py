"""NATS feedback loop when a shadow observation rule is promoted to production (Prompt 200)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SUBJECT = "tarka.hypothesis.promoted"


def promotion_feedback_subject() -> str:
    return (os.environ.get("RULE_ENGINE_PROMOTION_FEEDBACK_SUBJECT") or DEFAULT_SUBJECT).strip()


def is_observation_promotion(rule: dict[str, Any]) -> bool:
    meta = rule.get("metadata")
    return isinstance(meta, dict) and meta.get("promoted_from") == "observation"


def build_promotion_feedback_payload(
    rule: dict[str, Any],
    *,
    entity_ids: list[str],
    rule_version: int | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    rid = str(rule.get("id") or "").strip()
    return {
        "event": "rule_promoted_to_production",
        "rule_id": rid,
        "rule_version": rule_version,
        "tenant_id": tenant_id,
        "promoted_from": "observation",
        "entity_ids": entity_ids,
        "entity_count": len(entity_ids),
        "marked_at": datetime.now(UTC).isoformat(),
    }


async def publish_promotion_feedback(
    rule: dict[str, Any],
    *,
    entity_ids: list[str],
    rule_version: int | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """
    Publish ``tarka.hypothesis.promoted`` so the orchestrator graph worker can set ``high_risk`` on User vertices.
    """
    subject = promotion_feedback_subject()
    payload = build_promotion_feedback_payload(
        rule,
        entity_ids=entity_ids,
        rule_version=rule_version,
        tenant_id=tenant_id,
    )
    nats_url = (os.environ.get("RULE_ENGINE_NATS_URL") or os.environ.get("NATS_URL") or "").strip()
    if not nats_url:
        logger.warning(
            "promotion_feedback_nats_skipped rule_id=%s entity_count=%s",
            payload.get("rule_id"),
            len(entity_ids),
        )
        return {"ok": True, "nats_subject": None, **payload}

    import nats

    nc = await nats.connect(nats_url)
    try:
        await nc.publish(subject, json.dumps(payload, default=str).encode("utf-8"))
        await nc.flush()
    finally:
        await nc.drain()
    logger.info(
        "promotion_feedback_published subject=%s rule_id=%s entity_count=%s version=%s",
        subject,
        payload.get("rule_id"),
        len(entity_ids),
        rule_version,
    )
    return {"ok": True, "nats_subject": subject, **payload}


async def emit_observation_promotion_feedback(
    rule: dict[str, Any],
    *,
    rule_version: int | None = None,
    tenant_id: str = "default",
    duckdb_path: str | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    """
    Collect DuckDB shadow-rule matches and publish the graph-hardening NATS event.
    """
    if not is_observation_promotion(rule):
        return {"ok": True, "skipped": True, "reason": "not_observation_promotion"}

    entity_ids: list[str] = []
    try:
        from rule_engine.promotion_research import collect_matched_entity_ids_for_rule

        lb_raw = os.environ.get("PROMOTION_FEEDBACK_LOOKBACK_DAYS", "7").strip()
        lb = lookback_days if lookback_days is not None else int(lb_raw or "7")
        duck = duckdb_path or (os.environ.get("SIGNAL_DUCKDB_PATH") or os.environ.get("SHADOW_SCOUT_DUCKDB_PATH"))
        entity_ids = collect_matched_entity_ids_for_rule(
            rule,
            duckdb_path=duck,
            lookback_days=lb,
        )
    except Exception:
        logger.exception(
            "promotion_feedback_entity_collect_failed rule_id=%s",
            rule.get("id"),
        )

    return await publish_promotion_feedback(
        rule,
        entity_ids=entity_ids,
        rule_version=rule_version,
        tenant_id=tenant_id,
    )
