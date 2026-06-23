"""Administrative streaming export routes for ML retraining datasets."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from services.label_data_export import (
    LabelExportRangeError,
    export_content_disposition,
    export_media_type,
    iter_label_export_chunks,
    parse_export_format,
    parse_export_window,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Data export (admin)"])


def _require_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    session_factory = getattr(request.app.state, "audit_session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "audit_database_unconfigured",
                "message": "Label export requires ORCHESTRATOR_AUDIT_DATABASE_URL (or test override).",
            },
        )
    return session_factory


@router.get(
    "/labels/export",
    summary="Stream normalized labels + operational signals for ML export",
    description=(
        "Administrative export of deduplicated rows from ``normalized_labels`` and "
        "``operational_signals`` within an inclusive UTC date window. "
        "Streams via async SQLAlchemy cursors; default format is **jsonl** (one "
        "``tarka.label_export.v1`` record per line). Requires ``X-Auth-Token``."
    ),
    response_class=StreamingResponse,
    responses={
        422: {"description": "Invalid date window or format."},
        503: {"description": "Audit database not configured."},
    },
)
async def export_labels_dataset(
    request: Request,
    start_date: Annotated[
        str, Query(description="Inclusive UTC start date (YYYY-MM-DD or ISO-8601).")
    ],
    end_date: Annotated[str, Query(description="Inclusive UTC end date (YYYY-MM-DD or ISO-8601).")],
    format: Annotated[
        str, Query(description="Export encoding: jsonl (default) or json array.")
    ] = "jsonl",
) -> StreamingResponse:
    try:
        window = parse_export_window(start_date=start_date, end_date=end_date)
        export_format = parse_export_format(format)
    except LabelExportRangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_export_window", "message": str(exc)},
        ) from exc

    session_factory = _require_session_factory(request)
    logger.info(
        "label_export_started start=%s end=%s format=%s",
        window.start.isoformat(),
        window.end.isoformat(),
        export_format.value,
    )

    return StreamingResponse(
        iter_label_export_chunks(
            session_factory,
            window=window,
            export_format=export_format,
        ),
        media_type=export_media_type(export_format),
        headers={
            "Content-Disposition": export_content_disposition(
                window=window, export_format=export_format
            ),
            "X-Tarka-Export-Schema": "tarka.label_export.v1",
        },
    )
