"""Streaming ML-oriented export from ``normalized_labels`` and ``operational_signals``."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import Enum
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.normalized_labels import NormalizedLabelORM
from models.operational_signals import OperationalSignalORM

logger = logging.getLogger(__name__)

LABEL_EXPORT_SCHEMA = "tarka.label_export.v1"
_DEFAULT_STREAM_BATCH_SIZE = 500


class LabelExportFormat(str, Enum):
    JSONL = "jsonl"
    JSON = "json"


class LabelExportRangeError(ValueError):
    """Raised when export date parameters are invalid."""


@dataclass(frozen=True, slots=True)
class LabelExportWindow:
    start: datetime
    end: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


def parse_export_window(*, start_date: str, end_date: str) -> LabelExportWindow:
    start_raw = (start_date or "").strip()
    end_raw = (end_date or "").strip()
    if not start_raw or not end_raw:
        raise LabelExportRangeError("start_date and end_date are required")

    start = _parse_boundary_datetime(start_raw, bound="start")
    end = _parse_boundary_datetime(end_raw, bound="end")
    if end < start:
        raise LabelExportRangeError("end_date must be on or after start_date")
    return LabelExportWindow(start=start, end=end)


def parse_export_format(raw: str | None) -> LabelExportFormat:
    token = (raw or LabelExportFormat.JSONL.value).strip().lower()
    try:
        return LabelExportFormat(token)
    except ValueError as exc:
        raise LabelExportRangeError(f"format must be one of: jsonl, json (got {raw!r})") from exc


def _parse_boundary_datetime(raw: str, *, bound: str) -> datetime:
    token = raw.strip()
    if not token:
        raise LabelExportRangeError(f"{bound} date must be non-empty")

    if "T" in token or token.endswith("Z") or "+" in token[10:]:
        try:
            dt = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LabelExportRangeError(f"invalid ISO datetime for {bound}: {raw!r}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt

    try:
        day = date.fromisoformat(token)
    except ValueError as exc:
        raise LabelExportRangeError(
            f"invalid date for {bound}: {raw!r} (expected YYYY-MM-DD or ISO-8601 datetime)",
        ) from exc

    if bound == "start":
        return datetime.combine(day, time.min, tzinfo=UTC)
    return datetime.combine(day, time.max, tzinfo=UTC).replace(microsecond=999999)


def _normalize_tags(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def normalized_label_export_record(
    row: NormalizedLabelORM, *, window: LabelExportWindow
) -> dict[str, Any]:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    tags = _normalize_tags(row.tags)
    return {
        "schema": LABEL_EXPORT_SCHEMA,
        "record_type": "normalized_label",
        "export_window": window.as_dict(),
        "id": str(row.id),
        "source_type": str(row.source_type),
        "source_id": str(row.source_id),
        "entity_id": str(row.entity_id),
        "ground_truth_class": str(row.ground_truth_class),
        "tags": tags,
        "propagated_to_consortium": bool(row.propagated_to_consortium),
        "created_at": created_at.isoformat(),
        "dedupe_key": f"normalized_label:{row.source_type}:{row.source_id}",
    }


def operational_signal_export_record(
    row: OperationalSignalORM, *, window: LabelExportWindow
) -> dict[str, Any]:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return {
        "schema": LABEL_EXPORT_SCHEMA,
        "record_type": "operational_signal",
        "export_window": window.as_dict(),
        "id": str(row.id),
        "idempotency_key": str(row.idempotency_key),
        "target_entity_id": str(row.target_entity_id),
        "signal_type": str(row.signal_type),
        "metadata": metadata,
        "created_at": created_at.isoformat(),
        "dedupe_key": f"operational_signal:{row.idempotency_key}",
    }


def _deduped_normalized_labels_stmt(*, window: LabelExportWindow) -> Any:
    latest = (
        select(
            NormalizedLabelORM.source_type.label("source_type"),
            NormalizedLabelORM.source_id.label("source_id"),
            func.max(NormalizedLabelORM.created_at).label("max_created_at"),
        )
        .where(
            NormalizedLabelORM.created_at >= window.start,
            NormalizedLabelORM.created_at <= window.end,
        )
        .group_by(NormalizedLabelORM.source_type, NormalizedLabelORM.source_id)
        .subquery("latest_normalized_labels")
    )
    return (
        select(NormalizedLabelORM)
        .join(
            latest,
            and_(
                NormalizedLabelORM.source_type == latest.c.source_type,
                NormalizedLabelORM.source_id == latest.c.source_id,
                NormalizedLabelORM.created_at == latest.c.max_created_at,
            ),
        )
        .order_by(NormalizedLabelORM.created_at.asc(), NormalizedLabelORM.id.asc())
    )


def _operational_signals_stmt(*, window: LabelExportWindow) -> Any:
    return (
        select(OperationalSignalORM)
        .where(
            OperationalSignalORM.created_at >= window.start,
            OperationalSignalORM.created_at <= window.end,
        )
        .order_by(OperationalSignalORM.created_at.asc(), OperationalSignalORM.id.asc())
    )


async def iter_label_export_records(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    window: LabelExportWindow,
    batch_size: int = _DEFAULT_STREAM_BATCH_SIZE,
) -> AsyncIterator[dict[str, Any]]:
    """
    Stream deduplicated export rows from ``normalized_labels`` and ``operational_signals``.

    Uses async SQLAlchemy streaming cursors (``session.stream`` + ``yield_per``) per table.
    """
    label_stmt = _deduped_normalized_labels_stmt(window=window)
    signal_stmt = _operational_signals_stmt(window=window)

    async with session_factory() as session:
        label_result = await session.stream(label_stmt.execution_options(yield_per=batch_size))
        try:
            async for row in label_result.scalars():
                yield normalized_label_export_record(row, window=window)
        finally:
            await label_result.close()

        signal_result = await session.stream(signal_stmt.execution_options(yield_per=batch_size))
        try:
            async for row in signal_result.scalars():
                yield operational_signal_export_record(row, window=window)
        finally:
            await signal_result.close()


async def iter_label_export_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    window: LabelExportWindow,
    export_format: LabelExportFormat,
    batch_size: int = _DEFAULT_STREAM_BATCH_SIZE,
) -> AsyncIterator[bytes]:
    """Encode export records as streaming ``jsonl`` or JSON array bytes."""
    if export_format == LabelExportFormat.JSONL:
        async for record in iter_label_export_records(
            session_factory,
            window=window,
            batch_size=batch_size,
        ):
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            yield line.encode("utf-8")
        return

    yield b"[\n"
    first = True
    async for record in iter_label_export_records(
        session_factory,
        window=window,
        batch_size=batch_size,
    ):
        prefix = b"" if first else b",\n"
        first = False
        yield prefix + json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    yield b"\n]\n"


def export_media_type(export_format: LabelExportFormat) -> str:
    if export_format == LabelExportFormat.JSONL:
        return "application/x-ndjson"
    return "application/json"


def export_content_disposition(
    *, window: LabelExportWindow, export_format: LabelExportFormat
) -> str:
    start_token = window.start.date().isoformat()
    end_token = window.end.date().isoformat()
    ext = "jsonl" if export_format == LabelExportFormat.JSONL else "json"
    return f'attachment; filename="tarka-labels-{start_token}_{end_token}.{ext}"'
