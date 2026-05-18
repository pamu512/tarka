"""Compliance export: lifecycle case + graph snapshot + rule-engine (Rust) trace as a signed ZIP."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.models.cases import CaseORM
from orchestrator.models.decision import DecisionORM
from tarka_shared.audit_trail import AuditLog, Case as ShadowCase

EXPORT_CASE_JSON = "case.json"
EXPORT_GRAPH_SNAPSHOT_JSON = "graph_snapshot.json"
EXPORT_RUST_TRACE_JSON = "rust_trace.json"
EXPORT_MANIFEST_JSON = "manifest.json"
EXPORT_SIGNATURE_TXT = "signature.txt"


class CaseExportNotFoundError(LookupError):
    """No ``lifecycle_cases`` row for the requested ``case_id``."""


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, default=_json_default, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _build_zip_bytes(
    *,
    case_doc: dict[str, Any],
    graph_doc: dict[str, Any] | list[Any] | None,
    rust_doc: dict[str, Any],
    hmac_key: bytes,
) -> bytes:
    """Synchronous ZIP construction (call from ``asyncio.to_thread`` for large bundles)."""
    blobs = {
        EXPORT_CASE_JSON: _json_bytes(case_doc),
        EXPORT_GRAPH_SNAPSHOT_JSON: _json_bytes(graph_doc if graph_doc is not None else {}),
        EXPORT_RUST_TRACE_JSON: _json_bytes(rust_doc),
    }
    manifest = {
        "version": 1,
        "files": {name: hashlib.sha256(body).hexdigest() for name, body in sorted(blobs.items())},
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature_hex = (
        hmac.new(hmac_key, manifest_bytes, hashlib.sha256).hexdigest() if hmac_key else ""
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in blobs.items():
            zf.writestr(name, body)
        zf.writestr(EXPORT_MANIFEST_JSON, manifest_bytes)
        zf.writestr(EXPORT_SIGNATURE_TXT, (signature_hex + "\n").encode("ascii"))
    return buf.getvalue()


async def fetch_compliance_export_documents(
    *,
    audit_session_factory: async_sessionmaker[AsyncSession],
    case_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | list[Any] | None, dict[str, Any]]:
    """
    Load the same JSON payloads used for compliance ZIP export (case, shadow graph snapshot, Rust trace).

    Raises :class:`CaseExportNotFoundError` when ``lifecycle_cases.case_id`` is unknown.
    """
    cid = (case_id or "").strip()
    if not cid or len(cid) > 64 or "\x00" in cid:
        raise ValueError("invalid case_id")

    async with audit_session_factory() as session:
        row = await session.scalar(select(CaseORM).where(CaseORM.case_id == cid))
        if row is None:
            raise CaseExportNotFoundError(cid)

        log = await session.get(AuditLog, int(row.transaction_id))
        shadow: ShadowCase | None = None
        if log is not None:
            shadow = await session.get(ShadowCase, log.case_id)

        dec = await session.scalar(
            select(DecisionORM)
            .where(DecisionORM.entity_id == row.entity_id)
            .order_by(DecisionORM.created_at.desc())
            .limit(1),
        )

        case_doc = {
            "lifecycle_case": {
                "case_id": row.case_id,
                "entity_id": row.entity_id,
                "user_link_key": row.user_link_key,
                "status": row.status,
                "priority": int(row.priority),
                "assignee_id": row.assignee_id,
                "transaction_id": int(row.transaction_id),
                "opened_at": row.opened_at,
            },
            "shadow_case": None
            if shadow is None
            else {
                "id": shadow.id,
                "tenant_id": shadow.tenant_id,
                "name": shadow.name,
                "status": shadow.status,
                "dataset_path": shadow.dataset_path,
                "is_active": bool(shadow.is_active),
                "assigned_to": shadow.assigned_to,
                "created_at": shadow.created_at,
                "updated_at": shadow.updated_at,
            },
        }

        graph_doc = shadow.graph_snapshot if shadow is not None else None

        if dec is not None:
            rust_doc = {
                "format": "lekh_decision.v1",
                "description": (
                    "Rule-engine evaluation trace and raw payload (Rust evaluator in integrated deployments)."
                ),
                "entity_id": dec.entity_id,
                "decision_row_id": int(dec.id),
                "final_decision": dec.final_decision,
                "created_at": dec.created_at,
                "execution_trace": dec.execution_trace_json,
                "actions": dec.actions_json,
                "blocking_rule_id": dec.blocking_rule_id,
                "raw_rule_engine": dec.raw_rule_engine_json,
            }
        else:
            rust_doc = {
                "format": "lekh_decision.v1",
                "entity_id": row.entity_id,
                "execution_trace": [],
                "note": "no_decision_row_for_entity",
            }

    return case_doc, graph_doc, rust_doc


async def build_compliance_export_zip(
    *,
    audit_session_factory: async_sessionmaker[AsyncSession],
    case_id: str,
    hmac_key: bytes,
) -> bytes:
    """
    Load audit DB rows for ``lifecycle_cases.case_id``, assemble:

    * ``case.json`` — lifecycle case plus optional Shadow ``cases`` row (same DB).
    * ``graph_snapshot.json`` — ``ShadowCase.graph_snapshot`` (empty object when unset).
    * ``rust_trace.json`` — latest ``decisions`` row for ``lifecycle_cases.entity_id`` (execution trace /
      raw rule-engine payload from the Rust-backed evaluator path in production).

    ZIP also contains ``manifest.json`` (file SHA-256s) and ``signature.txt`` (HMAC-SHA256 of manifest
    when ``hmac_key`` is non-empty).
    """
    case_doc, graph_doc, rust_doc = await fetch_compliance_export_documents(
        audit_session_factory=audit_session_factory,
        case_id=case_id,
    )
    return await asyncio.to_thread(
        _build_zip_bytes,
        case_doc=case_doc,
        graph_doc=graph_doc,
        rust_doc=rust_doc,
        hmac_key=hmac_key,
    )
