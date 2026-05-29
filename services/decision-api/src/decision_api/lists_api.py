"""CRUD API for whitelist, blacklist, and test bypass management."""

import logging
import os
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared")
)
from entity_lists import ALL_LIST_TYPES, ListStore  # noqa: E402

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/lists", tags=["lists"])

_store: ListStore | None = None


def get_store() -> ListStore:
    if _store is None:
        raise HTTPException(503, "List store not initialized")
    return _store


def set_store(store: ListStore) -> None:
    global _store
    _store = store


class AddEntryRequest(BaseModel):
    tenant_id: str
    entity_id: str
    reason: str = ""
    created_by: str = "admin"
    expires_at: str | None = None
    metadata: dict[str, Any] = {}


class RemoveEntryRequest(BaseModel):
    tenant_id: str
    entity_id: str


class BulkAddRequest(BaseModel):
    tenant_id: str
    entries: list[dict[str, Any]]


@router.get("/check/{tenant_id}/{entity_id}")
async def check_entity(tenant_id: str, entity_id: str):
    """Check if an entity is on any list. Returns the matching list and action."""
    store = get_store()
    result = await store.check(tenant_id, entity_id)
    return {
        "found": result.found,
        "list_type": result.list_type,
        "action": result.action,
        "reason": result.reason,
    }


@router.get("/{list_type}")
async def list_entries(list_type: str, tenant_id: str, limit: int = 200):
    """List all entries in a specific list."""
    if list_type not in ALL_LIST_TYPES:
        raise HTTPException(
            400, f"Invalid list_type. Must be one of: {', '.join(ALL_LIST_TYPES)}"
        )
    store = get_store()
    entries = await store.get_all(list_type, tenant_id, limit)
    return {
        "list_type": list_type,
        "tenant_id": tenant_id,
        "count": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.post("/{list_type}", status_code=201)
async def add_entry(list_type: str, body: AddEntryRequest):
    """Add an entity to a list (whitelist, blacklist, or test_bypass)."""
    if list_type not in ALL_LIST_TYPES:
        raise HTTPException(
            400, f"Invalid list_type. Must be one of: {', '.join(ALL_LIST_TYPES)}"
        )
    store = get_store()
    entry = await store.add(
        list_type,
        body.tenant_id,
        body.entity_id,
        reason=body.reason,
        created_by=body.created_by,
        expires_at=body.expires_at,
        metadata=body.metadata,
    )
    return entry.to_dict()


@router.delete("/{list_type}/{tenant_id}/{entity_id}")
async def remove_entry(list_type: str, tenant_id: str, entity_id: str):
    """Remove an entity from a list."""
    if list_type not in ALL_LIST_TYPES:
        raise HTTPException(
            400, f"Invalid list_type. Must be one of: {', '.join(ALL_LIST_TYPES)}"
        )
    store = get_store()
    removed = await store.remove(list_type, tenant_id, entity_id)
    if not removed:
        raise HTTPException(404, "Entry not found")
    return {"removed": True}


@router.post("/{list_type}/bulk", status_code=201)
async def bulk_add(list_type: str, body: BulkAddRequest):
    """Bulk add entities to a list."""
    if list_type not in ALL_LIST_TYPES:
        raise HTTPException(
            400, f"Invalid list_type. Must be one of: {', '.join(ALL_LIST_TYPES)}"
        )
    store = get_store()
    added = []
    for item in body.entries[:1000]:
        entry = await store.add(
            list_type,
            body.tenant_id,
            item.get("entity_id", ""),
            reason=item.get("reason", ""),
            created_by=item.get("created_by", "bulk"),
            expires_at=item.get("expires_at"),
            metadata=item.get("metadata", {}),
        )
        added.append(entry.to_dict())
    return {"added": len(added), "entries": added}


@router.get("/{list_type}/count")
async def count_entries(list_type: str, tenant_id: str):
    if list_type not in ALL_LIST_TYPES:
        raise HTTPException(
            400, f"Invalid list_type. Must be one of: {', '.join(ALL_LIST_TYPES)}"
        )
    store = get_store()
    c = await store.count(list_type, tenant_id)
    return {"list_type": list_type, "tenant_id": tenant_id, "count": c}


@router.get("/stats/{tenant_id}")
async def list_stats(tenant_id: str):
    """Get counts for all list types."""
    store = get_store()
    stats = {}
    for lt in ALL_LIST_TYPES:
        stats[lt] = await store.count(lt, tenant_id)
    return {"tenant_id": tenant_id, "stats": stats}
