"""Analyst failover kill-switches for graph and AI planes (Prompt 170)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_REDIS_KEY = "ops:failover:toggles"

_MEMORY: dict[str, Any] = {
    "graph_plane_disabled": False,
    "ai_plane_disabled": False,
    "updated_by": None,
    "reason": None,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _default_probe_urls() -> tuple[str, str]:
    graph = (
        os.environ.get("FAILOVER_GRAPH_PROBE_URL")
        or os.environ.get("GRAPH_SERVICE_URL")
        or "http://127.0.0.1:8001"
    ).strip()
    ai = (
        os.environ.get("FAILOVER_AI_PROBE_URL")
        or os.environ.get("SIGNAL_API_URL")
        or "http://127.0.0.1:8004"
    ).strip()
    return graph.rstrip("/"), ai.rstrip("/")


async def _probe_latency_ms(
    http: httpx.AsyncClient, base: str, path: str = "/v1/health"
) -> float | None:
    if not base:
        return None
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    t0 = time.perf_counter()
    try:
        r = await http.get(url, timeout=3.0)
        if r.status_code >= 500:
            return None
    except Exception as exc:
        logger.debug("failover probe failed %s: %s", url, exc)
        return None
    return round((time.perf_counter() - t0) * 1000.0, 2)


async def _load_toggles(redis_client: Any | None) -> dict[str, Any]:
    if redis_client is not None:
        try:
            raw = await redis_client.get(_REDIS_KEY)
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict):
                    return {
                        "graph_plane_disabled": bool(data.get("graph_plane_disabled")),
                        "ai_plane_disabled": bool(data.get("ai_plane_disabled")),
                        "updated_by": data.get("updated_by"),
                        "reason": data.get("reason"),
                    }
        except Exception as exc:
            logger.warning("failover_toggles redis read failed: %s", exc)
    return dict(_MEMORY)


async def _save_toggles(redis_client: Any | None, state: dict[str, Any]) -> None:
    _MEMORY.update(
        {
            "graph_plane_disabled": bool(state.get("graph_plane_disabled")),
            "ai_plane_disabled": bool(state.get("ai_plane_disabled")),
            "updated_by": state.get("updated_by"),
            "reason": state.get("reason"),
        },
    )
    if redis_client is None:
        return
    try:
        await redis_client.set(
            _REDIS_KEY,
            json.dumps(
                {
                    "graph_plane_disabled": _MEMORY["graph_plane_disabled"],
                    "ai_plane_disabled": _MEMORY["ai_plane_disabled"],
                    "updated_by": _MEMORY.get("updated_by"),
                    "reason": _MEMORY.get("reason"),
                },
                separators=(",", ":"),
            ),
        )
    except Exception as exc:
        logger.warning("failover_toggles redis write failed: %s", exc)
        raise


async def build_failover_toggles_payload(
    *,
    http: httpx.AsyncClient,
    redis_client: Any | None,
) -> dict[str, Any]:
    toggles = await _load_toggles(redis_client)
    graph_base, ai_base = _default_probe_urls()
    graph_ms = await _probe_latency_ms(http, graph_base)
    ai_ms = await _probe_latency_ms(http, ai_base)
    return {
        "graph_plane_disabled": toggles["graph_plane_disabled"],
        "ai_plane_disabled": toggles["ai_plane_disabled"],
        "graph_latency_ms_p95": graph_ms,
        "ai_latency_ms_p95": ai_ms,
        "updated_at": _now_iso(),
        "updated_by": toggles.get("updated_by"),
        "source": "live",
        "probe_hints": {"graph": graph_base, "ai": ai_base},
    }


async def apply_failover_toggles(
    *,
    redis_client: Any | None,
    graph_plane_disabled: bool,
    ai_plane_disabled: bool,
    actor_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    state = {
        "graph_plane_disabled": bool(graph_plane_disabled),
        "ai_plane_disabled": bool(ai_plane_disabled),
        "updated_by": (actor_id or "").strip() or None,
        "reason": (reason or "").strip() or None,
    }
    await _save_toggles(redis_client, state)
    return state
