"""
JanusGraph **proximity cache** warmer: when an identity (User) is blocked, walk **1-hop** neighbors
and set ``proximity_risk:{neighbor_id}`` = ``1`` in Redis for each neighbor's canonical external id
(``device_id``, ``user_id``, ``address``, …).

Env (Gremlin — same defaults as orchestrator Janus sidecar):

* ``GREMLIN_REMOTE_URL`` — default ``ws://127.0.0.1:8182/gremlin``
* ``GREMLIN_TRAVERSAL_SOURCE`` — default ``g``

Redis:

* ``REDIS_URL`` — required for :func:`warm_proximity_cache_after_block_from_env`
* ``PROXIMITY_RISK_REDIS_TTL_SEC`` — optional TTL (seconds) on each key

This module is importable with ``sys.path`` containing ``services/graph-service`` (hyphenated directory name).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

LABEL_USER = "User"
LABEL_DEVICE = "Device"
LABEL_IP = "IP"
LABEL_CARD = "Card"
LABEL_EMAIL = "Email"
LABEL_ADDRESS = "Address"
LABEL_ORDER = "Order"
LABEL_PASSPORT = "Passport"
LABEL_LISTING = "Listing"

PROXIMITY_RISK_PREFIX = "proximity_risk:"


def proximity_risk_key(neighbor_external_id: str) -> str:
    return f"{PROXIMITY_RISK_PREFIX}{neighbor_external_id}"


def neighbor_external_id_from_element_map(em: dict[Any, Any]) -> str | None:
    """Pick a stable string id from a Gremlin ``elementMap()`` row (TinkerPop / JanusGraph)."""
    try:
        from gremlin_python.process.traversal import T
    except ImportError:
        T = None  # type: ignore[assignment]

    def _label() -> str:
        if T is not None:
            v = em.get(T.label)
            if v is not None:
                return str(v)
        v = em.get("label")
        if isinstance(v, list) and v:
            return str(v[0])
        return str(v) if v is not None else ""

    lbl = _label()
    if lbl == LABEL_USER and em.get("user_id") is not None:
        return str(em["user_id"])
    if lbl == LABEL_DEVICE and em.get("device_id") is not None:
        return str(em["device_id"])
    if lbl == LABEL_IP and em.get("address") is not None:
        return str(em["address"])
    if lbl == LABEL_CARD and em.get("card_id") is not None:
        return str(em["card_id"])
    if lbl == LABEL_EMAIL and em.get("email") is not None:
        return str(em["email"])
    if lbl == LABEL_ADDRESS and em.get("line1") is not None:
        return str(em["line1"])
    if lbl == LABEL_ORDER and em.get("order_id") is not None:
        return str(em["order_id"])
    if lbl == LABEL_PASSPORT and em.get("passport_id") is not None:
        return str(em["passport_id"])
    if lbl == LABEL_LISTING and em.get("listing_id") is not None:
        return str(em["listing_id"])
    if em.get("external_id") is not None:
        return str(em["external_id"])
    return None


def gremlin_collect_one_hop_neighbor_ids(g: Any, *, blocked_user_id: str) -> list[str]:
    """
    Run a synchronous Gremlin traversal: ``User`` by ``user_id`` → ``both()`` 1-hop → ``elementMap()``;
    return deduped neighbor external ids (excludes the anchor user vertex; only adjacent vertices).
    """
    uid = (blocked_user_id or "").strip()
    if not uid:
        return []

    try:
        ems = g.V().has(LABEL_USER, "user_id", uid).both().dedup().elementMap().toList()
    except Exception:
        logger.exception("proximity_gremlin_one_hop_failed blocked_user_id=%s", uid)
        return []

    out: list[str] = []
    seen: set[str] = set()
    for em in ems:
        if not isinstance(em, dict):
            continue
        ext = neighbor_external_id_from_element_map(em)
        if not ext or ext == uid:
            continue
        if ext in seen:
            continue
        seen.add(ext)
        out.append(ext)
    return out


async def warm_proximity_cache_for_blocked_user(
    redis: Any,
    g: Any,
    *,
    blocked_user_id: str,
    ttl_seconds: int | None = None,
) -> list[str]:
    """
    Find 1-hop neighbors for the blocked user in JanusGraph and set ``proximity_risk:{id}`` = ``1`` in Redis.

    ``redis`` must be ``redis.asyncio.Redis`` (decode_responses recommended). Gremlin calls run in a thread.
    """
    ids = await asyncio.to_thread(
        gremlin_collect_one_hop_neighbor_ids, g, blocked_user_id=blocked_user_id
    )
    if not ids:
        return []
    ttl = ttl_seconds
    if ttl is None:
        raw = (os.environ.get("PROXIMITY_RISK_REDIS_TTL_SEC") or "").strip()
        if raw:
            try:
                ttl = max(1, int(raw))
            except ValueError:
                ttl = None
    pipe = redis.pipeline(transaction=False)
    for nid in ids:
        key = proximity_risk_key(nid)
        if ttl is not None:
            pipe.set(key, "1", ex=int(ttl))
        else:
            pipe.set(key, "1")
    await pipe.execute()
    logger.info(
        "proximity_cache_warmed blocked_user_id=%s neighbor_count=%s",
        blocked_user_id,
        len(ids),
    )
    return ids


def traversal_source_from_env() -> tuple[Any, Any]:
    """Build ``(g, connection)`` for JanusGraph (caller must ``connection.close()`` when done)."""
    try:
        from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
        from gremlin_python.structure.graph import Graph
    except ImportError as e:
        raise RuntimeError("gremlinpython is required") from e

    url = (os.environ.get("GREMLIN_REMOTE_URL") or "ws://127.0.0.1:8182/gremlin").strip()
    source = (os.environ.get("GREMLIN_TRAVERSAL_SOURCE") or "g").strip() or "g"
    conn = DriverRemoteConnection(url, source)
    g = Graph().traversal().withRemote(conn)
    return g, conn


async def warm_proximity_cache_after_block_from_env(blocked_user_id: str) -> list[str]:
    """Convenience: ``REDIS_URL`` + Gremlin env; closes Gremlin connection when finished."""
    from redis.asyncio import Redis

    rurl = (os.environ.get("REDIS_URL") or "").strip()
    if not rurl:
        raise RuntimeError("REDIS_URL is not set")
    redis = Redis.from_url(rurl, decode_responses=True)
    g, conn = traversal_source_from_env()
    try:
        return await warm_proximity_cache_for_blocked_user(
            redis, g, blocked_user_id=blocked_user_id
        )
    finally:
        try:
            await redis.aclose()
        except Exception:
            logger.debug("redis_close_failed", exc_info=True)
        try:
            conn.close()
        except Exception:
            logger.debug("gremlin_close_failed", exc_info=True)


async def warm_proximity_cache_for_neighbor_ids(
    redis: Any,
    neighbor_ids: list[str],
    *,
    ttl_seconds: int | None = None,
) -> list[str]:
    """Set proximity flags for an explicit neighbor id list (tests / callers that already ran Gremlin)."""
    ids = [n.strip() for n in neighbor_ids if (n or "").strip()]
    if not ids:
        return []
    pipe = redis.pipeline(transaction=False)
    for nid in ids:
        key = proximity_risk_key(nid)
        if ttl_seconds is not None:
            pipe.set(key, "1", ex=int(ttl_seconds))
        else:
            pipe.set(key, "1")
    await pipe.execute()
    return ids
