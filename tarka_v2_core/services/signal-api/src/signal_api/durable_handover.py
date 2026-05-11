"""Postgres audit append + NATS JetStream publish for unified signal ingest (durable intent handover)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from signal_api.middleware.audit_circuit import AuditPostgresCircuitBreaker
from uuid import UUID

from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema

logger = logging.getLogger(__name__)

_DEFAULT_SIGNAL_SUBJECT = "signals.raw"
_DEFAULT_STREAM_NAME = "SIGNALS"


def canonical_signal_json_bytes(body: UnifiedSignalSchema) -> bytes:
    """Deterministic UTF-8 JSON for signing (sorted keys, compact separators)."""
    payload = body.model_dump(mode="json", by_alias=True)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def integrity_hmac_sha256_hex(secret: str, canonical_bytes: bytes) -> str:
    key = secret.encode("utf-8")
    return hmac.new(key, canonical_bytes, hashlib.sha256).hexdigest()


def verify_integrity_hmac(secret: str, canonical_bytes: bytes, stored_hex: str) -> bool:
    expected = integrity_hmac_sha256_hex(secret, canonical_bytes)
    return hmac.compare_digest(expected, stored_hex.lower())


async def ensure_signals_jetstream_stream(js: Any) -> None:
    """Create JetStream stream covering ``signals.raw`` if missing."""
    from nats.js.api import StreamConfig, StorageType
    from nats.js.errors import NotFoundError

    stream_name = (os.environ.get("SIGNAL_NATS_STREAM") or _DEFAULT_STREAM_NAME).strip()
    subject = (os.environ.get("SIGNAL_NATS_SIGNALS_SUBJECT") or _DEFAULT_SIGNAL_SUBJECT).strip()
    try:
        await js.stream_info(stream_name)
    except NotFoundError:
        await js.add_stream(
            StreamConfig(
                name=stream_name,
                subjects=[subject],
                storage=StorageType.FILE,
            ),
        )
        logger.info("signal_jetstream_stream_created name=%s subjects=%s", stream_name, subject)


async def persist_audit_log(
    conn: Any,
    *,
    entity_id: UUID,
    raw_payload: dict[str, Any],
    integrity_signature: str,
    decision: str | None = None,
) -> None:
    if decision is None:
        decision = (os.environ.get("SIGNAL_AUDIT_DECISION") or "unified_signal.ingested").strip()[
            :512
        ]
    else:
        decision = decision.strip()[:512]
    await conn.execute(
        """
        INSERT INTO audit_logs (id, entity_id, raw_payload, decision, integrity_signature)
        VALUES (gen_random_uuid(), $1::uuid, $2::jsonb, $3, $4)
        """,
        entity_id,
        raw_payload,
        decision,
        integrity_signature,
    )


async def publish_signal_jetstream(js: Any, canonical_bytes: bytes) -> None:
    subject = (os.environ.get("SIGNAL_NATS_SIGNALS_SUBJECT") or _DEFAULT_SIGNAL_SUBJECT).strip()
    await js.publish(subject, canonical_bytes)


async def durable_intent_handover(
    *,
    pool: Any | None,
    js: Any | None,
    body: UnifiedSignalSchema,
    canonical_bytes: bytes,
    integrity_hex: str,
    audit_decision: str | None = None,
    circuit: AuditPostgresCircuitBreaker | None = None,
) -> None:
    """Background task: Postgres row + JetStream publish (errors logged, do not fail HTTP)."""
    raw_payload = body.model_dump(mode="json", by_alias=True)
    entity_id = body.session_id

    if pool is not None:
        if circuit is not None and circuit.is_degraded():
            logger.warning(
                "signal_audit_skipped_degraded_mode entity_id=%s",
                entity_id,
            )
        else:
            try:

                async def _persist_audit() -> None:
                    async with pool.acquire() as conn:
                        await persist_audit_log(
                            conn,
                            entity_id=entity_id,
                            raw_payload=raw_payload,
                            integrity_signature=integrity_hex,
                            decision=audit_decision,
                        )

                tout = circuit.effective_execute_timeout_sec() if circuit is not None else 0.0
                if tout > 0:
                    await asyncio.wait_for(_persist_audit(), timeout=tout)
                else:
                    await _persist_audit()
                if circuit is not None:
                    await circuit.record_success()
                logger.info("signal_audit_persisted entity_id=%s", entity_id)
            except asyncio.TimeoutError:
                if circuit is not None:
                    await circuit.record_timeout()
                logger.exception("signal_audit_persist_timeout entity_id=%s", entity_id)
            except Exception:
                if circuit is not None:
                    await circuit.record_non_timeout_failure()
                logger.exception("signal_audit_persist_failed entity_id=%s", entity_id)

    if js is not None:
        try:
            await publish_signal_jetstream(js, canonical_bytes)
            logger.info("signal_nats_published bytes=%s", len(canonical_bytes))
        except Exception:
            logger.exception("signal_nats_publish_failed entity_id=%s", entity_id)
