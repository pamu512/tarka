from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

from gremlin_python.driver.client import Client
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal

from .config import settings
from .entity_risk_score import SEARCH_PROP_KEYS

"""Shared Gremlin Server connection for JanusGraph backend (sync driver, thread offload)."""
log = logging.getLogger("graph-service.janus")

_conn: DriverRemoteConnection | None = None
_vertex_search_enabled = False
_indexes_checked = False

T = TypeVar("T")


def _schema_ensure_groovy() -> str:
    # Frozen allowlist identifiers only — never interpolate user q.
    key_decls: list[str] = []
    add_keys: list[str] = []
    status_keys = ["tenant_id", *SEARCH_PROP_KEYS]
    for i, key in enumerate(SEARCH_PROP_KEYS):
        key_decls.append(
            f"k{i} = mgmt.getPropertyKey('{key}')\n"
            f"if (k{i} == null) {{ k{i} = mgmt.makePropertyKey('{key}').dataType(String.class).make() }}"
        )
        add_keys.append(f"b.addKey(k{i}, Mapping.TEXTSTRING.asParameter())")
    status_loop = "\n".join(
        f"pk = mgmt.getPropertyKey('{k}'); "
        f"if (pk == null || idx.getIndexStatus(pk) != SchemaStatus.ENABLED) {{ allEnabled = false }}"
        for k in status_keys
    )
    decls = "\n".join(key_decls)
    adds = "\n".join(add_keys)
    return f"""
import org.apache.tinkerpop.gremlin.structure.Vertex
import org.janusgraph.core.schema.Mapping
import org.janusgraph.core.schema.SchemaStatus
mgmt = graph.openManagement()
try {{
  tid = mgmt.getPropertyKey('tenant_id')
  if (tid == null) {{ tid = mgmt.makePropertyKey('tenant_id').dataType(String.class).make() }}
  eid = mgmt.getPropertyKey('external_id')
  if (eid == null) {{ eid = mgmt.makePropertyKey('external_id').dataType(String.class).make() }}
  {decls}
  comp = mgmt.getGraphIndex('byTenantExternal')
  if (comp == null) {{
    mgmt.buildIndex('byTenantExternal', Vertex.class).addKey(tid).addKey(eid).unique().buildCompositeIndex()
  }}
  idx = mgmt.getGraphIndex('vertexSearch')
  if (idx == null) {{
    b = mgmt.buildIndex('vertexSearch', Vertex.class)
    b.addKey(tid, Mapping.STRING.asParameter())
    {adds}
    b.buildMixedIndex('search')
  }}
  mgmt.commit()
  mgmt = graph.openManagement()
  idx = mgmt.getGraphIndex('vertexSearch')
  if (idx == null) {{ mgmt.rollback(); return 'MISSING' }}
  allEnabled = true
  {status_loop}
  mgmt.rollback()
  return allEnabled ? 'ENABLED' : 'REGISTERED'
}} catch (Exception e) {{
  try {{ mgmt.rollback() }} catch (Exception ignored) {{}}
  return 'FAILED'
}}
"""


def vertex_search_index_enabled() -> bool:
    return _vertex_search_enabled


def ensure_janus_indexes() -> None:
    """Idempotent composite + mixed index ensure. Never wait for REINDEX. Never raise to HTTP."""
    global _vertex_search_enabled, _indexes_checked
    if _indexes_checked:
        return
    _indexes_checked = True
    client = None
    try:
        url = settings.janusgraph_gremlin_url.strip()
        src = settings.janusgraph_traversal_source.strip() or "g"
        client = Client(url, src)
        raw = client.submit(_schema_ensure_groovy()).all().result()
        status = str(raw[0] if raw else "FAILED").upper()
        _vertex_search_enabled = status == "ENABLED"
        if not _vertex_search_enabled:
            log.warning(
                "Janus mixed index vertexSearch status=%s; search uses capped tenant scan",
                status,
            )
    except Exception:
        log.exception(
            "Janus index ensure (byTenantExternal/vertexSearch) failed; lookups stay correct, search uses capped scan"
        )
        _vertex_search_enabled = False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as e:
                log.warning("Gremlin management client close: %s", e)


def get_traversal_source():
    """Return a GraphTraversalSource bound to the remote Gremlin Server."""
    global _conn
    if _conn is None:
        url = settings.janusgraph_gremlin_url.strip()
        src = settings.janusgraph_traversal_source.strip() or "g"
        log.info("JanusGraph Gremlin: connecting to %s traversal=%s", url, src)
        _conn = DriverRemoteConnection(url, src)
        ensure_janus_indexes()
    return traversal().withRemote(_conn)


def close_janus_connection() -> None:
    global _conn, _indexes_checked, _vertex_search_enabled
    if _conn is not None:
        try:
            _conn.close()
        except Exception as e:
            log.warning("Gremlin connection close: %s", e)
        _conn = None
    _indexes_checked = False
    _vertex_search_enabled = False


async def run_in_gremlin_thread(fn: Callable[[], T]) -> T:
    """Run blocking Gremlin traversal in a worker thread."""
    return await asyncio.to_thread(fn)
