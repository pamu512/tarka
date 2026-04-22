from __future__ import annotations

"""Shared Gremlin Server connection for JanusGraph backend (sync driver, thread offload)."""


import asyncio
import logging
from typing import Callable, TypeVar

from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal

from graph_service.config import settings

log = logging.getLogger("graph-service.janus")

_conn: DriverRemoteConnection | None = None

T = TypeVar("T")


def get_traversal_source():
    """Return a GraphTraversalSource bound to the remote Gremlin Server."""
    global _conn
    if _conn is None:
        url = settings.janusgraph_gremlin_url.strip()
        src = settings.janusgraph_traversal_source.strip() or "g"
        log.info("JanusGraph Gremlin: connecting to %s traversal=%s", url, src)
        _conn = DriverRemoteConnection(url, src)
    return traversal().withRemote(_conn)


def close_janus_connection() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception as e:
            log.warning("Gremlin connection close: %s", e)
        _conn = None


async def run_in_gremlin_thread(fn: Callable[[], T]) -> T:
    """Run blocking Gremlin traversal in a worker thread."""
    return await asyncio.to_thread(fn)
