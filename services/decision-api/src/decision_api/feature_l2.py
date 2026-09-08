"""L2 online feature serve. Empty FEATURE_STORE_URL = off (L1/raw)."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

ENTITY_TYPES = frozenset(
    {"user", "device", "courier", "merchant", "promo", "payment_instrument"}
)

router = APIRouter(prefix="/v1/features", tags=["feature-l2"])
_LOCK = threading.Lock()
_STORE: dict[tuple[str, str, str], list[dict[str, Any]]] = {}


def feature_store_url() -> str:
    return (os.environ.get("FEATURE_STORE_URL") or "").strip()


def resolve_feature_source(*, redis_url: str = "") -> str:
    if feature_store_url():
        return "l2"
    redis = (
        redis_url
        or os.environ.get("REDIS_URL")
        or os.environ.get("TARKA_REDIS_URL")
        or ""
    ).strip()
    return "l1" if redis else "raw"


def upsert_feature(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    features: dict[str, Any],
    as_of: str | None = None,
) -> None:
    et = (entity_type or "").strip().lower()
    if et not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {sorted(ENTITY_TYPES)}")
    ts = as_of or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    key = (tenant_id, et, entity_id)
    with _LOCK:
        rows = list(_STORE.get(key) or [])
        rows.append({"as_of": ts, "features": dict(features)})
        _STORE[key] = rows


def get_features(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    as_of: str | None = None,
) -> dict[str, Any]:
    et = (entity_type or "").strip().lower()
    if et not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {sorted(ENTITY_TYPES)}")
    want = as_of or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    key = (tenant_id, et, entity_id)
    with _LOCK:
        rows = list(_STORE.get(key) or [])
    chosen: dict[str, Any] = {}
    for row in rows:
        if str(row.get("as_of") or "") <= want:
            chosen = dict(row.get("features") or {})
    return chosen


def write_event_features(
    *,
    tenant_id: str,
    entity_id: str,
    payload: dict[str, Any] | None,
    event_ts: str | None = None,
) -> None:
    if not payload:
        return
    features = {
        k: payload[k]
        for k in ("amount", "event_count_1h", "sum_amount_1h")
        if k in payload
    }
    if not features:
        return
    upsert_feature(
        tenant_id=tenant_id,
        entity_type="user",
        entity_id=entity_id,
        features=features,
        as_of=event_ts,
    )


def backfill_from_jsonl(path: str | os.PathLike[str], *, tenant_id: str) -> int:
    n = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        tid = str(row.get("tenant_id") or tenant_id).strip()
        eid = str(row.get("entity_id") or "").strip()
        if not eid:
            continue
        feats = row.get("features") if isinstance(row.get("features"), dict) else {}
        write_event_features(
            tenant_id=tid,
            entity_id=eid,
            payload=feats or row,
            event_ts=str(row.get("as_of") or row.get("created_at") or "") or None,
        )
        n += 1
    return n


def holdout_split(
    rows: list[dict[str, Any]], *, cutoff: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train, hold = [], []
    for row in rows:
        ts = str(row.get("as_of") or row.get("created_at") or "")
        if ts and ts < cutoff:
            train.append(row)
        else:
            hold.append(row)
    return train, hold


@router.get("/{entity_type}/{entity_id}")
async def serve_features(
    entity_type: str,
    entity_id: str,
    tenant_id: str = Query(..., min_length=1),
    as_of: str | None = Query(default=None),
) -> dict[str, Any]:
    if not feature_store_url():
        return {
            "feature_source": resolve_feature_source(),
            "features": {},
            "l2": "off",
        }
    try:
        t0 = time.monotonic()
        feats = get_features(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            as_of=as_of,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000.0
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "invalid_entity_type", "message": str(exc)}
        ) from exc
    return {
        "feature_source": "l2",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "as_of": as_of,
        "features": feats,
        "elapsed_ms": elapsed_ms,
    }
