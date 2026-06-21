"""Case workflow status values (persisted in SQLite / Postgres where applicable)."""

from __future__ import annotations

from typing import Literal

CaseStatus = Literal["INVESTIGATING", "FLAGGED", "CLEARED"]

CASE_STATUSES: tuple[CaseStatus, ...] = ("INVESTIGATING", "FLAGGED", "CLEARED")

DEFAULT_CASE_STATUS: CaseStatus = "INVESTIGATING"


def normalize_case_status(value: str | None) -> CaseStatus:
    if not value or not str(value).strip():
        return DEFAULT_CASE_STATUS
    u = str(value).strip().upper()
    if u in CASE_STATUSES:
        return u  # type: ignore[return-value]
    return DEFAULT_CASE_STATUS
