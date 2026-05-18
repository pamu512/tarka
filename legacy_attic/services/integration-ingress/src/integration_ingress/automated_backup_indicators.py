"""Automated backup indicators — last Postgres / JanusGraph snapshot times (Prompt 173)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

BackupStatus = Literal["ok", "warn", "stale", "unknown", "missing"]

_REDIS_POSTGRES_AT = "ops:backup:postgres:last_snapshot_at"
_REDIS_JANUS_AT = "ops:backup:janusgraph:last_snapshot_at"
_REDIS_POSTGRES_META = "ops:backup:postgres:meta"
_REDIS_JANUS_META = "ops:backup:janusgraph:meta"

_STORES: tuple[dict[str, str], ...] = (
    {"id": "postgres", "label": "PostgreSQL", "subdir": "postgres", "glob": ("*.sql", "*.sql.gz", "*.dump", "*.dump.gz", "*.tar", "*.tar.gz")},
    {
        "id": "janusgraph",
        "label": "JanusGraph",
        "subdir": "janusgraph",
        "glob": ("*.groovy", "*.json", "*.tar", "*.tar.gz", "*.zip", "*.bak"),
    },
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso_ts(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _classify_backup_age(age_seconds: float | None, *, ok_hours: float, warn_hours: float) -> BackupStatus:
    if age_seconds is None:
        return "unknown"
    if age_seconds < 0:
        return "unknown"
    ok_sec = ok_hours * 3600.0
    warn_sec = warn_hours * 3600.0
    if age_seconds <= ok_sec:
        return "ok"
    if age_seconds <= warn_sec:
        return "warn"
    return "stale"


def _newest_file_in_dir(root: Path, patterns: tuple[str, ...]) -> tuple[datetime | None, Path | None, int | None]:
    if not root.is_dir():
        return None, None, None
    newest_at: datetime | None = None
    newest_path: Path | None = None
    newest_size: int | None = None
    for pat in patterns:
        for path in root.glob(pat):
            if not path.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if newest_at is None or mtime > newest_at:
                newest_at = mtime
                newest_path = path
                try:
                    newest_size = int(path.stat().st_size)
                except OSError:
                    newest_size = None
    return newest_at, newest_path, newest_size


def _read_status_json(backup_dir: Path) -> dict[str, Any]:
    path = backup_dir / "backup_status.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("backup_status.json unreadable: %s", exc)
        return {}


async def _redis_snapshot(
    redis_client: Any | None,
    at_key: str,
    meta_key: str,
) -> tuple[datetime | None, dict[str, Any]]:
    if redis_client is None:
        return None, {}
    try:
        raw_at = await redis_client.get(at_key)
        at = _parse_iso_ts(raw_at.decode() if isinstance(raw_at, bytes) else raw_at)
        meta_raw = await redis_client.get(meta_key)
        meta: dict[str, Any] = {}
        if meta_raw:
            text = meta_raw.decode() if isinstance(meta_raw, bytes) else str(meta_raw)
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    meta = parsed
            except json.JSONDecodeError:
                meta = {"artifact_hint": text[:500]}
        return at, meta
    except Exception as exc:
        logger.warning("backup indicator redis read failed %s: %s", at_key, exc)
        return None, {}


def _store_row(
    *,
    store_id: str,
    label: str,
    last_at: datetime | None,
    artifact_hint: str | None,
    size_bytes: int | None,
    source: str,
    ok_hours: float,
    warn_hours: float,
    schedule_hint: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    age_seconds: float | None = None
    if last_at is not None:
        age_seconds = max(0.0, (now - last_at).total_seconds())
    status = _classify_backup_age(age_seconds, ok_hours=ok_hours, warn_hours=warn_hours)
    if last_at is None:
        status = "missing"
    return {
        "store": store_id,
        "label": label,
        "last_snapshot_at": last_at.isoformat() if last_at else None,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "status": status,
        "artifact_hint": artifact_hint,
        "size_bytes": size_bytes,
        "source": source,
        "schedule_hint": schedule_hint,
    }


async def build_automated_backup_indicators_payload(
    *,
    redis_client: Any | None,
    backup_dir: str | None = None,
    ok_hours: float | None = None,
    warn_hours: float | None = None,
) -> dict[str, Any]:
    """Build JSON for ``GET /v1/ops/automated-backup-indicators``."""
    ok_h = float(ok_hours if ok_hours is not None else os.environ.get("BACKUP_OK_MAX_AGE_HOURS", "26"))
    warn_h = float(warn_hours if warn_hours is not None else os.environ.get("BACKUP_WARN_MAX_AGE_HOURS", "50"))
    base_dir = Path(
        backup_dir
        or os.environ.get("TARKA_BACKUP_DIR")
        or os.environ.get("BACKUP_DIR")
        or "data/backups",
    ).expanduser()
    status_json = _read_status_json(base_dir)

    postgres_schedule = os.environ.get("BACKUP_POSTGRES_SCHEDULE_HINT", "Daily 02:00 UTC (pg_dump)")
    janus_schedule = os.environ.get("BACKUP_JANUSGRAPH_SCHEDULE_HINT", "Daily 03:30 UTC (gremlin backup)")

    redis_pg_at, redis_pg_meta = await _redis_snapshot(redis_client, _REDIS_POSTGRES_AT, _REDIS_POSTGRES_META)
    redis_jg_at, redis_jg_meta = await _redis_snapshot(redis_client, _REDIS_JANUS_AT, _REDIS_JANUS_META)

    pg_dir = base_dir / "postgres"
    jg_dir = base_dir / "janusgraph"
    pg_file_at, pg_file_path, pg_file_size = _newest_file_in_dir(pg_dir, _STORES[0]["glob"])  # type: ignore[arg-type]
    jg_file_at, jg_file_path, jg_file_size = _newest_file_in_dir(jg_dir, _STORES[1]["glob"])  # type: ignore[arg-type]

    json_pg = status_json.get("postgres") if isinstance(status_json.get("postgres"), dict) else {}
    json_jg = status_json.get("janusgraph") if isinstance(status_json.get("janusgraph"), dict) else {}

    def _pick(
        store_id: str,
        label: str,
        redis_at: datetime | None,
        redis_meta: dict[str, Any],
        file_at: datetime | None,
        file_path: Path | None,
        file_size: int | None,
        json_row: dict[str, Any],
        schedule_hint: str,
    ) -> dict[str, Any]:
        candidates: list[tuple[str, datetime | None, str | None, int | None]] = []
        if redis_at:
            candidates.append(
                (
                    "redis",
                    redis_at,
                    str(redis_meta.get("artifact_hint") or redis_meta.get("path") or "") or None,
                    int(redis_meta["size_bytes"]) if isinstance(redis_meta.get("size_bytes"), (int, float)) else None,
                ),
            )
        if file_at:
            candidates.append(
                (
                    "filesystem",
                    file_at,
                    str(file_path.relative_to(base_dir)) if file_path and base_dir in file_path.parents else str(file_path),
                    file_size,
                ),
            )
        js_at = _parse_iso_ts(str(json_row.get("last_snapshot_at") or json_row.get("at") or "") or None)
        if js_at:
            candidates.append(
                (
                    "backup_status.json",
                    js_at,
                    str(json_row.get("artifact_hint") or json_row.get("path") or "") or None,
                    int(json_row["size_bytes"]) if isinstance(json_row.get("size_bytes"), (int, float)) else None,
                ),
            )
        if not candidates:
            return _store_row(
                store_id=store_id,
                label=label,
                last_at=None,
                artifact_hint=str(base_dir / store_id),
                size_bytes=None,
                source="unconfigured",
                ok_hours=ok_h,
                warn_hours=warn_h,
                schedule_hint=schedule_hint,
            )
        source, last_at, artifact, size = max(candidates, key=lambda c: c[1] or datetime.min.replace(tzinfo=UTC))
        return _store_row(
            store_id=store_id,
            label=label,
            last_at=last_at,
            artifact_hint=artifact,
            size_bytes=size,
            source=source,
            ok_hours=ok_h,
            warn_hours=warn_h,
            schedule_hint=schedule_hint,
        )

    stores = [
        _pick(
            "postgres",
            "PostgreSQL",
            redis_pg_at,
            redis_pg_meta,
            pg_file_at,
            pg_file_path,
            pg_file_size,
            json_pg,
            postgres_schedule,
        ),
        _pick(
            "janusgraph",
            "JanusGraph",
            redis_jg_at,
            redis_jg_meta,
            jg_file_at,
            jg_file_path,
            jg_file_size,
            json_jg,
            janus_schedule,
        ),
    ]

    return {
        "updated_at": _now_iso(),
        "backup_dir": str(base_dir),
        "thresholds_hours": {"ok": ok_h, "warn": warn_h},
        "stores": stores,
    }
