"""Tarka consortium HTTP adapter (share, check, feedback, trust, JSON Lines ingest)."""

from .client import (
    ConsortiumAdapter,
    ingest_json_lines,
    load_adapter_from_env,
    validate_ingest_record,
)

__all__ = [
    "ConsortiumAdapter",
    "ingest_json_lines",
    "load_adapter_from_env",
    "validate_ingest_record",
]
