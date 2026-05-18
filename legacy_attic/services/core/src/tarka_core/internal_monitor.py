"""Centralized audit logging when an exception is intentionally suppressed."""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("tarka.internal_monitor")


class InternalMonitor:
    """Structured audit trail for errors that are handled without re-raising."""

    @staticmethod
    def log_suppressed_error(
        exc: BaseException,
        *,
        context: str,
        domain: str = "general",
        level: int = logging.WARNING,
        **extra: Any,
    ) -> None:
        """Emit a log record with exception info so suppressed faults remain observable."""
        payload = {
            "internal_monitor": True,
            "suppressed_exception": True,
            "context": context,
            "domain": domain,
            "exc_type": type(exc).__name__,
            **extra,
        }
        _log.log(
            level,
            "suppressed_error context=%s domain=%s exc_type=%s",
            context,
            domain,
            type(exc).__name__,
            exc_info=exc,
            extra=payload,
        )
