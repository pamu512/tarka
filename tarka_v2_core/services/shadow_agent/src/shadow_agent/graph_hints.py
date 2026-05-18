"""Resolve graph anchor fields from a :class:`~ingestor.schemas.TransactionSchema` (shadow-local)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestor.schemas import TransactionSchema


@dataclass(frozen=True, slots=True)
class AnchorHints:
    user_id: str | None
    device_id: str | None
    ip: str | None


def _meta_str(meta: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        raw = meta.get(k)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            s = str(raw).strip()
        elif isinstance(raw, str):
            s = raw.strip()
        else:
            continue
        if not s or len(s) > 512 or "\x00" in s:
            continue
        return s
    return None


def graph_anchor_hints(tx: TransactionSchema) -> AnchorHints:
    meta = tx.metadata or {}
    return AnchorHints(
        user_id=_meta_str(meta, "user_id", "graph_user_id", "user"),
        device_id=_meta_str(meta, "device_id", "device_fingerprint", "graph_device_id"),
        ip=_meta_str(meta, "ip", "ip_address", "graph_ip"),
    )


def listing_id_from_transaction(tx: TransactionSchema) -> str | None:
    """Resolve marketplace listing id for review-graph tools (orchestrator-aligned keys)."""
    return _meta_str(
        tx.metadata or {},
        "listing_id",
        "review_listing_id",
        "marketplace_listing_id",
    )
