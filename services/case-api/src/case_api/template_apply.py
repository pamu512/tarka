"""Resolve and apply investigation templates / built-in playbooks (Marble #56)."""

from __future__ import annotations

import uuid
from typing import Any

from audit_trail import AuditTrail
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.builtin_playbooks import PLAYBOOKS
from case_api.models import Case, CaseComment, InvestigationTemplate
from case_api.schemas import CaseOut


def _normalize_apply_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(raw)
    labels = list(cfg.get("labels") or [])
    et = cfg.get("escalation_team")
    if et and str(et).strip():
        labels.append(f"escalation_team:{str(et).strip()}")
    cfg["labels"] = labels
    return cfg


def _mutation_slice_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("status", "priority", "assigned_team", "labels"):
        if k in cfg and cfg[k] is not None:
            out[k] = cfg[k]
    return out


def apply_case_payload_to_case(case: Case, payload: dict[str, Any]) -> None:
    if "status" in payload and payload["status"]:
        case.status = str(payload["status"])
    if "priority" in payload and payload["priority"]:
        case.priority = str(payload["priority"])
    if "assigned_team" in payload:
        case.assigned_team = payload["assigned_team"]
    if "labels" in payload and isinstance(payload["labels"], list):
        existing = set(case.labels or [])
        case.labels = sorted(existing | {str(x) for x in payload["labels"] if str(x).strip()})


async def resolve_playbook_or_template(
    session: AsyncSession,
    tenant_id: str,
    playbook_field: str | None,
) -> tuple[str | None, dict[str, Any], uuid.UUID | None]:
    """Return (trail_key, apply_config, template_uuid_or_none). Empty when no template requested."""
    if not playbook_field or not str(playbook_field).strip():
        return None, {}, None
    pid = str(playbook_field).strip()
    if pid in PLAYBOOKS:
        return pid, dict(PLAYBOOKS[pid]), None
    try:
        tid = uuid.UUID(pid)
    except ValueError:
        raise HTTPException(422, "unknown playbook_id or investigation template id") from None
    row = await session.scalar(
        select(InvestigationTemplate).where(
            InvestigationTemplate.id == tid,
            InvestigationTemplate.tenant_id == tenant_id,
        ),
    )
    if not row:
        raise HTTPException(422, "unknown investigation template id for tenant")
    cfg = dict(row.apply_config or {})
    return str(row.id), cfg, row.id


async def apply_investigation_template_transaction(
    *,
    trail: AuditTrail,
    session: AsyncSession,
    case: Case,
    apply_config: dict[str, Any],
    trail_key: str,
    actor: str,
    trail_action: str,
    tenant_id: str,
    template_uuid: uuid.UUID | None = None,
) -> None:
    cfg = _normalize_apply_config(apply_config)
    mut = _mutation_slice_from_config(cfg)
    old_state = CaseOut.model_validate(case).model_dump(mode="json")
    apply_case_payload_to_case(case, mut)
    if "default_owner" in cfg:
        dv = cfg.get("default_owner")
        case.default_owner = (str(dv).strip() or None) if dv not in (None, "") else None
    if "sla_hours" in cfg:
        try:
            raw_h = int(cfg["sla_hours"])
        except (TypeError, ValueError):
            raw_h = 0
        case.sla_hours_override = raw_h if 1 <= raw_h <= 8760 else None
    if template_uuid is not None:
        case.applied_template_id = template_uuid
    if cfg.get("comment"):
        session.add(CaseComment(case_id=case.id, author="playbook", body=str(cfg["comment"])))
    await session.commit()
    await session.refresh(case)
    new_state = CaseOut.model_validate(case).model_dump(mode="json")
    diff = trail.diff(old_state, new_state)
    if diff:
        await trail.record(
            session,
            actor=actor,
            action=trail_action,
            resource_type="case",
            resource_id=str(case.id),
            changes={"template": trail_key, **diff},
            tenant_id=tenant_id,
        )
        await session.commit()
