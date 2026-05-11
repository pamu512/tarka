"""Client ``session_nonce`` + SHA-256 in-transit integrity (mirrors ``sdk/browser/src/integrity.ts``)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema

logger = logging.getLogger(__name__)


def redis_ingest_nonce_key(session_id: str) -> str:
    return f"signal:ingest:nonce:{session_id.strip()}"


def canonical_transit_wire_bytes(body: UnifiedSignalSchema) -> bytes:
    """
    UTF-8 JSON identical to the browser helper: **wire aliases**, sorted keys, **excluding** ``n``,
    ``ih``, and server-only geo aliases ``gc`` / ``gct`` so the hash input is stable across client/server.
    """
    d = body.model_dump(mode="json", by_alias=True)
    d.pop("ih", None)
    d.pop("n", None)
    d.pop("gc", None)
    d.pop("gct", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def expected_client_integrity_hex(body: UnifiedSignalSchema) -> str:
    assert body.session_nonce is not None
    wire = canonical_transit_wire_bytes(body)
    nonce = body.session_nonce.encode("utf-8")
    return hashlib.sha256(wire + b"|" + nonce).hexdigest()


def _consteq_utf8(a: str, b: str) -> bool:
    ab, bb = a.encode("utf-8"), b.encode("utf-8")
    if len(ab) != len(bb):
        return False
    return hmac.compare_digest(ab, bb)


def _consteq_hex64(a: str, b: str) -> bool:
    return _consteq_utf8(a.lower(), b.lower())


async def verify_in_transit_integrity(redis: Any, body: UnifiedSignalSchema) -> bool:
    """
    Returns **True** when check passes or is skipped (no ``n``/``ih`` pair).

    When ``n`` and ``ih`` are set: Redis must hold the same nonce for ``session_id`` and the hash
    must match :func:`expected_client_integrity_hex`.
    """
    if body.session_nonce is None or body.client_integrity_hash is None:
        return True

    sid = str(body.session_id)
    key = redis_ingest_nonce_key(sid)
    raw = await redis.get(key)
    if raw is None:
        logger.warning("transit_integrity_missing_server_nonce session_id=%s", sid)
        return False
    stored = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    if not _consteq_utf8(stored, body.session_nonce):
        logger.warning("transit_integrity_nonce_mismatch session_id=%s", sid)
        return False

    exp = expected_client_integrity_hex(body)
    if not _consteq_hex64(exp, body.client_integrity_hash or ""):
        logger.warning("transit_integrity_hash_mismatch session_id=%s", sid)
        return False
    return True


def transit_audit_decision(ok: bool) -> str | None:
    """``None`` = use default ``SIGNAL_AUDIT_DECISION``; else explicit Postgres ``decision``."""
    if ok:
        return None
    return (os.environ.get("SIGNAL_AUDIT_DECISION_TAMPERED") or "TAMPERED_IN_TRANSIT").strip()[:512]
