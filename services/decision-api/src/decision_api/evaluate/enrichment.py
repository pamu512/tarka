"""Evaluate enrichment step wrappers (re-exported from main until further extraction).

ponytail: wrappers still close over main-module circuits/HTTP; this module is the
stable import path for the evaluate package. Next cut moves circuit clients here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from decision_api.schemas import EvaluateRequest


async def fetch_graph_risk_wrapped(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
    graph_checkpoint: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any] | None:
    from decision_api import main as m

    return await m._fetch_graph_risk_wrapped(
        http,
        tenant_id,
        entity_id,
        degrade_tags,
        tenant_flags,
        graph_checkpoint,
        event_type,
    )


async def fetch_feature_snapshot_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    redis_tag_list: list[str],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> dict[str, Any]:
    from decision_api import main as m

    return await m._fetch_feature_snapshot_wrapped(
        http, body, redis_tag_list, degrade_tags, tenant_flags
    )
