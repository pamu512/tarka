"""Second AGE writer: map a foreign record onto the same Person evaluate uses.

Join is the record field the operator named. Wrong key = a different Person.
No fuzzy match. Nodes and the link carry source= so Hunt can tell the pipes apart.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ObjectMapping(BaseModel):
    join_field: str
    object_field: str
    object_type: str
    relationship: str


class MappedIngestRequest(BaseModel):
    tenant_id: str
    source: str
    mapping: ObjectMapping
    record: dict[str, Any] = Field(default_factory=dict)


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, bool, int, float)) or value is None


def plan_mapped_object(
    *, source: str, mapping: ObjectMapping, record: dict[str, Any]
) -> dict[str, Any]:
    src = (source or "").strip()
    if not src:
        raise ValueError("source is required")
    join_field = (mapping.join_field or "").strip()
    object_field = (mapping.object_field or "").strip()
    object_type = (mapping.object_type or "").strip()
    relationship = (mapping.relationship or "").strip()
    if not join_field or not object_field or not object_type or not relationship:
        raise ValueError("mapping needs join_field, object_field, object_type, relationship")
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    person_id = str(record.get(join_field) or "").strip()
    object_id = str(record.get(object_field) or "").strip()
    if not person_id:
        raise ValueError("join key empty")
    if not object_id:
        raise ValueError("object key empty")
    extra = {k: v for k, v in record.items() if k not in {join_field, object_field} and _scalar(v)}
    return {
        "person_id": person_id,
        "object_id": object_id,
        "object_type": object_type,
        "relationship": relationship,
        "source": src,
        "person_props": {"source": src},
        "object_props": {"source": src, **extra},
        "link_props": {"source": src},
    }


async def ingest_mapped_object(body: MappedIngestRequest) -> dict[str, Any]:
    from graph_contract import UnsignedGraphToken

    from .graph_runtime import create_link, upsert_entity

    plan = plan_mapped_object(source=body.source, mapping=body.mapping, record=body.record)
    tid = (body.tenant_id or "").strip()
    if not tid:
        raise ValueError("tenant_id is required")
    try:
        await upsert_entity(tid, "Person", plan["person_id"], dict(plan["person_props"]))
        await upsert_entity(tid, plan["object_type"], plan["object_id"], dict(plan["object_props"]))
        await create_link(
            tid,
            plan["person_id"],
            plan["object_id"],
            plan["relationship"],
            dict(plan["link_props"]),
        )
    except UnsignedGraphToken:
        raise
    return {
        "tenant_id": tid,
        "source": plan["source"],
        "person_id": plan["person_id"],
        "object_id": plan["object_id"],
        "object_type": plan["object_type"],
        "relationship": plan["relationship"],
    }
