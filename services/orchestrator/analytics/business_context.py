"""
Opt-in DuckDB / analytics-plane **financial spend** aggregations.

These queries are intentionally **not** invoked on live transaction ingest or automated
rule-evaluation paths. Callers must pass ``include_business_context=True`` explicitly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from analytics.provider import AnalyticsProvider

logger = logging.getLogger(__name__)

_BUSINESS_CONTEXT_SKIPPED: dict[str, Any] = {
    "source": "analytics",
    "available": False,
    "business_context_skipped": True,
    "reason": "include_business_context_false",
}


def business_context_skipped_payload(*, source: str = "analytics") -> dict[str, Any]:
    """Shape returned when financial aggregations were not requested."""
    return {**_BUSINESS_CONTEXT_SKIPPED, "source": source}


def marketplace_user_stats(
    analytics: AnalyticsProvider,
    user_id: str,
    *,
    include_business_context: bool = False,
) -> dict[str, Any]:
    if not include_business_context:
        return business_context_skipped_payload()
    return {**analytics.marketplace_user_stats(user_id), "available": True}


def cluster_loss_for_device_hashes(
    analytics: AnalyticsProvider,
    device_hashes: Sequence[str],
    *,
    include_business_context: bool = False,
) -> dict[str, Any]:
    if not include_business_context:
        return {
            **business_context_skipped_payload(),
            "cluster_loss": None,
            "linked_txn_count": 0,
            "distinct_session_count": 0,
            "device_hashes_used": [],
        }
    return analytics.cluster_loss_for_device_hashes(device_hashes)


def cluster_spend_velocity_for_network(
    analytics: AnalyticsProvider,
    *,
    transaction_entity_ids: Sequence[str],
    network_user_ids: Sequence[str],
    days: int = 30,
    include_business_context: bool = False,
) -> dict[str, Any]:
    if not include_business_context:
        return business_context_skipped_payload()
    return analytics.cluster_spend_velocity_for_network(
        transaction_entity_ids=list(transaction_entity_ids),
        network_user_ids=list(network_user_ids),
        days=days,
    )


async def cluster_spend_velocity_for_network_async(
    analytics: AnalyticsProvider,
    *,
    transaction_entity_ids: Sequence[str],
    network_user_ids: Sequence[str],
    days: int = 30,
    include_business_context: bool = False,
) -> dict[str, Any]:
    if not include_business_context:
        return business_context_skipped_payload()
    try:
        return await asyncio.to_thread(
            analytics.cluster_spend_velocity_for_network,
            transaction_entity_ids=list(transaction_entity_ids),
            network_user_ids=list(network_user_ids),
            days=days,
        )
    except Exception:
        logger.exception("business_context_cluster_spend_velocity_failed")
        return {"error": "duck_cluster_failed", "available": False}


def attach_cluster_loss_to_metrics(
    duck_metrics: dict[str, Any],
    cluster_loss: dict[str, Any],
) -> None:
    if cluster_loss.get("business_context_skipped"):
        return
    duck_metrics["cluster_loss"] = cluster_loss["cluster_loss"]
    duck_metrics["cluster_loss_txn_count"] = cluster_loss["linked_txn_count"]
    duck_metrics["cluster_loss_session_count"] = cluster_loss["distinct_session_count"]
    duck_metrics["cluster_loss_device_scope"] = cluster_loss["device_hashes_used"]
