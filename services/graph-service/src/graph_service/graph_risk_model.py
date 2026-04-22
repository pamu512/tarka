from __future__ import annotations
import asyncio
from typing import Any

import httpx

from graph_service.config import settings

"""Optional GNN-beta adapter for graph risk scoring."""

async def score_graph_risk_beta(
    tenant_id: str,
    entity_id: str,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any] | None:
    """Best-effort beta scorer; never raises to caller."""
    base_url = settings.graph_gnn_beta_url.strip()
    if not base_url:
        return None

    timeout = max(0.1, float(timeout_seconds or settings.graph_gnn_beta_timeout_seconds))
    request_payload = {"tenant_id": tenant_id, "entity_id": entity_id}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await asyncio.wait_for(
                client.post(f"{base_url.rstrip('/')}/v1/graph-risk", json=request_payload),
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    try:
        risk_score = max(0.0, min(100.0, float(data.get("risk_score", 0.0))))
    except (TypeError, ValueError):
        risk_score = 0.0

    reasons = data.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    return {
        "model": "gnn-beta",
        "risk_score": risk_score,
        "reasons": [str(x).strip() for x in reasons if str(x).strip()][:8],
    }
