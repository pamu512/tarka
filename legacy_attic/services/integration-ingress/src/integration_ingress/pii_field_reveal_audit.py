"""Audit-logged PII field reveal/hide events from analyst UI (Prompt 177)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PiiRevealAction = Literal["reveal", "hide"]
PiiFieldKind = Literal["email", "phone", "financial", "generic"]

ALLOWED_KINDS = frozenset({"email", "phone", "financial", "generic"})
ALLOWED_ACTIONS = frozenset({"reveal", "hide"})


def fingerprint_value(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:32]


def masked_preview(value: str, *, field_kind: str) -> str:
    s = (value or "").strip()
    if not s:
        return "—"
    kind = (field_kind or "generic").lower()
    if kind == "email" and "@" in s:
        local, domain = s.split("@", 1)
        return f"{local[:2]}***@{domain}"[:128]
    if kind == "phone":
        digits = "".join(c for c in s if c.isdigit())
        if len(digits) >= 4:
            return f"***{digits[-4:]}"[:128]
        return "****"
    if kind == "financial" and len(s) > 4:
        return f"****{s[-4:]}"[:128]
    if len(s) > 4:
        return f"{s[:2]}{'*' * min(8, len(s) - 4)}{s[-2:]}"[:128]
    return "****"


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "actor_id": row.actor_id,
        "action": row.action,
        "field_kind": row.field_kind,
        "field_path": row.field_path,
        "context_type": row.context_type,
        "context_id": row.context_id,
        "value_fingerprint": row.value_fingerprint,
        "masked_preview": row.masked_preview,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def record_pii_field_reveal_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    action: str,
    field_kind: str,
    field_path: str,
    context_type: str,
    context_id: str | None,
    value_fingerprint: str,
    masked_preview_value: str,
) -> dict[str, Any]:
    from integration_ingress.models import PiiFieldRevealAudit

    act = (action or "").strip().lower()
    if act not in ALLOWED_ACTIONS:
        raise ValueError(f"invalid action {action!r}")
    kind = (field_kind or "generic").strip().lower()
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"invalid field_kind {field_kind!r}")
    fp = (value_fingerprint or "").strip()
    if len(fp) < 8:
        raise ValueError("value_fingerprint required")
    row = PiiFieldRevealAudit(
        id=uuid.uuid4(),
        tenant_id=(tenant_id or "demo").strip() or "demo",
        actor_id=(actor_id or "")[:128] or None,
        action=act,
        field_kind=kind,
        field_path=(field_path or "unknown")[:256],
        context_type=(context_type or "ui")[:64],
        context_id=(context_id or "")[:256] or None,
        value_fingerprint=fp[:64],
        masked_preview=(masked_preview_value or "****")[:128],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row)


async def list_pii_field_reveal_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    from integration_ingress.models import PiiFieldRevealAudit

    tid = (tenant_id or "demo").strip() or "demo"
    cap = max(1, min(int(limit), 500))
    rows = (
        await session.scalars(
            select(PiiFieldRevealAudit)
            .where(PiiFieldRevealAudit.tenant_id == tid)
            .order_by(PiiFieldRevealAudit.created_at.desc())
            .limit(cap),
        )
    ).all()
    return [_row_to_dict(r) for r in rows]
