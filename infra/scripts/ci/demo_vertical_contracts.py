"""Shared assertions for the evaluate → case → ingest demo (used by smoke script + unit tests)."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def check_evaluate_response(data: dict[str, Any]) -> None:
    """Minimal shape for POST /v1/decisions/evaluate success."""
    for key in ("decision", "score", "trace_id", "inference_context"):
        assert key in data, f"evaluate response missing {key!r}"
    assert isinstance(data["inference_context"], dict)
    assert data["inference_context"].get("schema_version")
    # UUID from API
    raw = str(data["trace_id"])
    UUID(raw)


def check_create_case_response(data: dict[str, Any]) -> None:
    """Minimal shape for POST /v1/cases 201."""
    for key in ("id", "tenant_id", "entity_id", "trace_id", "status"):
        assert key in data, f"case create response missing {key!r}"


def check_event_ingest_accepted(status_code: int) -> None:
    assert status_code == 200, f"ingest expected 200, got {status_code}"


def check_frontend_reachable(status_code: int) -> None:
    assert status_code in (200, 301, 302, 304), (
        f"frontend health expected 2xx/3xx, got {status_code}"
    )
