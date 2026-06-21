"""Audit-first persistence failures (fail-closed ingestion and shadow evaluate)."""

from __future__ import annotations


class AuditPersistenceError(RuntimeError):
    """
    Raised when a decision path cannot durably append ``audit_logs`` (or related rows).

    Callers map ``http_status`` to FastAPI responses (503 unconfigured / unavailable, 500 persist).
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "audit_persist_failed",
        http_status: int = 503,
        entity_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.http_status = http_status
        self.entity_id = entity_id

    @classmethod
    def unconfigured(cls, *, component: str = "orchestrator") -> AuditPersistenceError:
        return cls(
            f"{component} audit database is not configured",
            error_code="audit_database_unconfigured",
            http_status=503,
        )

    @classmethod
    def persist_failed(
        cls,
        *,
        entity_id: str | None = None,
        component: str = "orchestrator",
        http_status: int = 500,
    ) -> AuditPersistenceError:
        msg = f"{component} failed to persist audit log"
        if entity_id:
            msg = f"{msg} (entity_id={entity_id})"
        return cls(
            msg,
            error_code="audit_persist_failed",
            http_status=http_status,
            entity_id=entity_id,
        )
