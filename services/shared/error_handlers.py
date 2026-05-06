from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


def _support_id() -> str:
    return uuid.uuid4().hex[:12]


def _payload(
    *,
    code: str,
    message: str,
    status_code: int,
    retryable: bool = False,
    support_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "status_code": status_code,
            "retryable": retryable,
            "support_id": support_id,
            "details": details or {},
        }
    }


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    sid = _support_id()
    details: dict[str, Any] | None = None
    if isinstance(exc.detail, dict):
        # Preserve structured client errors (e.g. idempotency policy) in details.
        details = dict(exc.detail)
        message = str(details.get("message") or details.get("error") or exc.status_code)
    elif isinstance(exc.detail, str):
        message = exc.detail
    else:
        message = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(
            code=f"http_{exc.status_code}",
            message=message,
            status_code=exc.status_code,
            retryable=exc.status_code in {429, 502, 503, 504},
            support_id=sid,
            details=details,
        ),
    )


async def validation_exception_handler(_: Request, exc: ValidationError) -> JSONResponse:
    sid = _support_id()
    details = {"errors": exc.errors()}
    return JSONResponse(
        status_code=400,
        content=_payload(
            code="validation_error",
            message="Request validation failed",
            status_code=400,
            support_id=sid,
            details=details,
        ),
    )


async def sqlalchemy_exception_handler(_: Request, __: SQLAlchemyError) -> JSONResponse:
    sid = _support_id()
    return JSONResponse(
        status_code=503,
        content=_payload(
            code="database_unavailable",
            message="Database temporarily unavailable",
            status_code=503,
            retryable=True,
            support_id=sid,
        ),
    )


async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    sid = _support_id()
    return JSONResponse(
        status_code=500,
        content=_payload(
            code="internal_error",
            message="Unexpected server error",
            status_code=500,
            retryable=True,
            support_id=sid,
        ),
    )


def setup_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
