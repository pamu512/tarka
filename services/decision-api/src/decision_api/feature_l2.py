"""L2 online feature serve + optional writers. Empty FEATURE_STORE_URL = off (no L2 writes)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from event_time import parse_event_time_to_unix

log = logging.getLogger("decision-api.feature-l2")

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
    return fallback_feature_source(redis_url=redis_url)


def fallback_feature_source(*, redis_url: str = "") -> str:
    """L1/raw only. Never l2 — used when L2 is off, miss, or timeout."""
    redis = (
        redis_url
        or os.environ.get("REDIS_URL")
        or os.environ.get("TARKA_REDIS_URL")
        or ""
    ).strip()
    return "l1" if redis else "raw"


def evaluate_as_of_iso(
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> str:
    for src in (
        metadata if isinstance(metadata, dict) else None,
        payload if isinstance(payload, dict) else None,
    ):
        if not src:
            continue
        for key in ("event_time", "event_ts", "occurred_at", "as_of", "created_at"):
            raw = src.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    new_ts = parse_event_time_to_unix(ts)
    with _LOCK:
        rows = list(_STORE.get(key) or [])
        replaced = False
        if new_ts is not None:
            for i, row in enumerate(rows):
                row_ts = parse_event_time_to_unix(row.get("as_of"))
                if row_ts is not None and row_ts == new_ts:
                    rows[i] = {"as_of": ts, "features": dict(features)}
                    replaced = True
                    break
        if not replaced:
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
    want_raw = as_of or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    want = parse_event_time_to_unix(want_raw)
    if want is None:
        want = datetime.now(UTC).timestamp()
    key = (tenant_id, et, entity_id)
    with _LOCK:
        rows = list(_STORE.get(key) or [])
    chosen: dict[str, Any] = {}
    chosen_ts: float | None = None
    for row in rows:
        row_ts = parse_event_time_to_unix(row.get("as_of"))
        if row_ts is None or row_ts > want:
            continue
        if chosen_ts is None or row_ts >= chosen_ts:
            chosen = dict(row.get("features") or {})
            chosen_ts = row_ts
    return chosen


async def fetch_l2_features(
    http: Any,
    *,
    tenant_id: str,
    entity_id: str,
    entity_type: str = "user",
    as_of: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any] | None:
    """GET L2. Empty FEATURE_STORE_URL = skip. Timeout/miss = None. Never raises."""
    base = feature_store_url()
    if not base:
        return None
    if timeout_s is None:
        try:
            from decision_api.config import settings

            timeout_s = float(settings.eval_step_feature_snapshot_timeout_seconds)
        except Exception:
            timeout_s = 2.5
    et = (entity_type or "user").strip().lower() or "user"
    url = f"{base.rstrip('/')}/v1/features/{et}/{entity_id}"
    params: dict[str, str] = {"tenant_id": tenant_id}
    if as_of:
        params["as_of"] = as_of
    try:
        r = await http.get(url, params=params, timeout=timeout_s)
        status = getattr(r, "status_code", None)
        if status is None or int(status) >= 400:
            return None
        payload = r.json() if hasattr(r, "json") else None
        if callable(payload):
            payload = await payload
        if not isinstance(payload, dict):
            return None
        feats = payload.get("features")
        if not isinstance(feats, dict) or not feats:
            return None
        return dict(feats)
    except Exception:
        log.debug("l2_serve_fail_soft", exc_info=True)
        return None


async def evaluate_l2_read(
    http: Any,
    *,
    tenant_id: str,
    entity_id: str,
    as_of: str | None = None,
    redis_url: str = "",
    entity_type: str = "user",
    timeout_s: float | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Evaluate L2 hop. Hit → (features, l2). Off/miss/timeout → (None, l1|raw)."""
    feats = await fetch_l2_features(
        http,
        tenant_id=tenant_id,
        entity_id=entity_id,
        entity_type=entity_type,
        as_of=as_of,
        timeout_s=timeout_s,
    )
    if feats:
        return feats, "l2"
    return None, fallback_feature_source(redis_url=redis_url)


def write_event_features(
    *,
    tenant_id: str,
    entity_id: str,
    payload: dict[str, Any] | None,
    event_ts: str | None = None,
) -> None:
    """Stream hook. Empty FEATURE_STORE_URL = no L2 write. Fail-soft."""
    if not feature_store_url():
        return
    if not payload:
        return
    features = {
        k: payload[k]
        for k in ("amount", "event_count_1h", "sum_amount_1h")
        if k in payload
    }
    if not features:
        return
    ts = (event_ts or "").strip() or evaluate_as_of_iso(None, payload)
    try:
        upsert_feature(
            tenant_id=tenant_id,
            entity_type="user",
            entity_id=entity_id,
            features=features,
            as_of=ts,
        )
    except Exception:
        log.debug("l2_write_fail_soft", exc_info=True)


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
