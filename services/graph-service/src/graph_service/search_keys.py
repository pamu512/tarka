"""SQL prefix search for Hunt. AGE Cypher property indexes do not work (apache/age#2348)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("graph-service.search_keys")

_OUTCOME_RANK = {"deny": 0, "review": 1, "flag": 2, "allow": 4}
_ENSURED = False


def normalize_search_key(raw: object) -> str:
    return str(raw or "").strip().lower()


def outcome_rank(outcome: str | None) -> int:
    token = str(outcome or "").strip().lower()
    if not token:
        return 3
    return _OUTCOME_RANK.get(token, 3)


def keys_from_upsert(
    entity_type: str, external_id: str, properties: dict[str, Any] | None
) -> list[tuple[str, str]]:
    kind = str(entity_type or "").strip()
    eid = normalize_search_key(external_id)
    if not eid:
        return []
    if kind.lower() == "device":
        return [("external_id", eid)]
    if kind.lower() != "person":
        return []
    out: list[tuple[str, str]] = [("external_id", eid)]
    props = properties or {}
    email = normalize_search_key(props.get("email"))
    phone = normalize_search_key(props.get("phone"))
    if email:
        out.append(("email", email))
    if phone:
        out.append(("phone", phone))
    return out


def _is_person(hit: dict[str, Any]) -> bool:
    return "Person" in [str(x) for x in (hit.get("labels") or [])]


def sort_search_hits(hits: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for raw in hits:
        eid = str(raw.get("entity_external_id") or raw.get("entity_id") or "").strip()
        if not eid:
            continue
        prev = best.get(eid)
        if prev is None:
            best[eid] = raw
            continue
        if _is_person(raw) and not _is_person(prev):
            best[eid] = raw
            continue
        if _is_person(raw) == _is_person(prev) and outcome_rank(
            raw.get("last_outcome")
        ) < outcome_rank(prev.get("last_outcome")):
            best[eid] = raw
    rows = list(best.values())
    rows.sort(
        key=lambda h: (
            outcome_rank(h.get("last_outcome")),
            str(h.get("entity_external_id") or h.get("entity_id") or ""),
        )
    )
    out: list[dict[str, Any]] = []
    for h in rows[: max(1, int(limit))]:
        eid = str(h.get("entity_external_id") or h.get("entity_id") or "")
        kind = str(h.get("key_kind") or "external_id")
        out.append(
            {
                "entity_id": eid,
                "tenant_id": h.get("tenant_id"),
                "labels": list(h.get("labels") or []),
                "last_outcome": h.get("last_outcome"),
                "matched_on": kind if kind != "external_id" else "external_id",
                "scored": False,
                "risk_score": None,
                "via": None,
            }
        )
    return out


async def _pool():
    from .config import settings
    import asyncpg

    return await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4)


_sql_pool = None


async def _acquire():
    global _sql_pool
    if _sql_pool is None:
        _sql_pool = await _pool()
    return _sql_pool


async def ensure_search_keys_table() -> None:
    global _ENSURED
    if _ENSURED:
        return
    pool = await _acquire()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_keys (
                tenant_id TEXT NOT NULL,
                entity_external_id TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'Person',
                key_kind TEXT NOT NULL,
                key_norm TEXT NOT NULL,
                last_outcome TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, key_kind, key_norm)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_search_keys_tenant_norm ON search_keys (tenant_id, key_norm)"
        )
    _ENSURED = True


async def upsert_search_keys(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any] | None,
) -> None:
    keys = keys_from_upsert(entity_type, external_id, properties)
    if not keys:
        return
    outcome = str((properties or {}).get("last_outcome") or "").strip() or None
    etype = "Device" if str(entity_type).lower() == "device" else "Person"
    await ensure_search_keys_table()
    pool = await _acquire()
    async with pool.acquire() as conn:
        for kind, norm in keys:
            await conn.execute(
                """
                INSERT INTO search_keys (
                    tenant_id, entity_external_id, entity_type, key_kind, key_norm, last_outcome
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (tenant_id, key_kind, key_norm) DO UPDATE SET
                    entity_external_id = EXCLUDED.entity_external_id,
                    entity_type = EXCLUDED.entity_type,
                    last_outcome = EXCLUDED.last_outcome,
                    updated_at = now()
                """,
                tenant_id,
                external_id,
                etype,
                kind,
                norm,
                outcome,
            )


async def search_prefix(
    tenant_id: str,
    q: str,
    label: str | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], bool] | None:
    needle = normalize_search_key(q)
    if len(needle) < 2:
        return [], False
    try:
        await ensure_search_keys_table()
        pool = await _acquire()
    except Exception:
        log.warning("search_keys_unavailable", exc_info=True)
        return None
    like = f"{needle}%"
    cap = max(1, int(limit))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT entity_external_id, entity_type, key_kind, last_outcome
            FROM search_keys
            WHERE tenant_id = $1 AND key_norm LIKE $2
            LIMIT $3
            """,
            tenant_id,
            like,
            cap + 1,
        )
    hits = [
        {
            "tenant_id": tenant_id,
            "entity_external_id": r["entity_external_id"],
            "labels": [r["entity_type"]],
            "key_kind": r["key_kind"],
            "last_outcome": r["last_outcome"],
        }
        for r in rows
    ]
    if label:
        want = str(label).strip()
        hits = [h for h in hits if want in (h.get("labels") or [])]
    truncated = len(hits) > cap
    return sort_search_hits(hits, limit=cap), truncated
