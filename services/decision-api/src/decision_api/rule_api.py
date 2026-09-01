from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.backtest_promote_gate import backtest_before_promote_gate
from decision_api.config import settings
from decision_api.db import get_session
from decision_api.json_rules import get_rule_hit_telemetry, load_rules
from decision_api.models import BacktestRun
from decision_api.rule_pack_validation import validate_rule_pack as _validate_rule_pack
from decision_api.live_rule_slip import maybe_park_live_rule_slip
from decision_api.shadow_auto_promote import (
    activate_shadow_pack,
    load_provision,
    maybe_auto_promote_shadow,
    save_provision,
)
from decision_api.shadow import (
    get_observation_stats,
    get_observations,
    load_shadow_rules,
)
from decision_api.vertical_packs import (
    evaluate_kill_criteria,
    get_vertical_pack,
    list_vertical_packs,
)

"""REST API for rule CRUD — serves the visual rule builder."""
router = APIRouter(prefix="/v1/rules", tags=["rules"])
logger = logging.getLogger(__name__)
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,120}\.json$")
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9_-]+")

from auth_rbac import require_role  # noqa: E402


class Condition(BaseModel):
    field: str
    op: str = "eq"
    value: Any = None


class RuleIn(BaseModel):
    id: str = ""
    when: list[Condition] = Field(default_factory=list)
    """Optional native JSON AST (AND/OR + leaves). Mutually exclusive with non-empty ``when`` on evaluate."""
    when_ast: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    score_delta: float = 0
    description: str = ""


class TagRuleIn(BaseModel):
    id: str = ""
    any_tag: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_delta: float = 0
    description: str = ""


class RulePackIn(BaseModel):
    name: str
    rules: list[RuleIn] = Field(default_factory=list)
    tag_rules: list[TagRuleIn] = Field(default_factory=list)
    canary_percent: float | None = Field(default=None, ge=0, le=100)
    effective_at: str | None = Field(default=None, max_length=64)
    approved_by: str | None = Field(default=None, max_length=256)


class PromoteVerticalPackBody(BaseModel):
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1_score: float = Field(default=0.0, ge=0, le=1)
    false_positive_rate: float | None = Field(default=None, ge=0, le=1)
    events_evaluated: int = Field(ge=0)
    backtest_job_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional succeeded warehouse backtest job; required when TARKA_REQUIRE_BACKTEST_BEFORE_PROMOTE=1",
    )


def _rules_dir() -> Path:
    p = Path(settings.rules_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _change_log_path() -> Path:
    return _rules_dir() / "rule_change_log.jsonl"


def _append_rule_change(
    action: str,
    filename: str,
    *,
    actor: str = "api",
    detail: dict[str, Any] | None = None,
) -> None:
    """Append-only audit for lightweight governance (not a full CMDB)."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "file": filename,
        "actor": actor,
        "detail": detail or {},
    }
    p = _change_log_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _list_pack_paths() -> dict[str, Path]:
    base = _rules_dir()
    return {p.name: p for p in base.glob("*.json") if p.is_file()}


def _existing_pack_path(filename: str) -> Path:
    if not _SAFE_FILENAME_RE.fullmatch(filename):
        raise HTTPException(400, "invalid filename")
    path = _list_pack_paths().get(filename)
    if not path:
        raise HTTPException(404, "pack not found")
    return path


def _slugify_pack_name(name: str) -> str:
    raw = name.strip().lower().replace(" ", "_")
    slug = _SAFE_SLUG_RE.sub("", raw)
    slug = slug.strip("._-")
    if not slug:
        raise HTTPException(400, "invalid pack name")
    return slug[:80]


def _new_pack_path(prefix: str = "pack") -> Path:
    # Avoid any user-controlled filesystem path fragments.
    return _rules_dir() / f"{prefix}_{uuid.uuid4().hex[:12]}.json"


def _read_all_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    d = _rules_dir()
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = f.name
            packs.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return packs


def _actor_from_headers(x_actor: str | None) -> str:
    a = (x_actor or os.environ.get("RULE_CHANGE_ACTOR") or "api").strip()
    return a[:256] if a else "api"


def _require_force_live_human(x_actor: str | None) -> str:
    """Force-live is a human fingerprint. Do not use RULE_CHANGE_ACTOR fallback."""
    actor = (x_actor or "").strip()
    low = actor.lower()
    if not actor or low.startswith("scout") or "assist" in low:
        raise HTTPException(403, "force_live_human_only")
    return actor[:256]


def _force_live_two_person_required() -> bool:
    return (os.environ.get("RULE_FORCE_LIVE_TWO_PERSON") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _require_force_live_approver(actor: str, x_approver: str | None) -> str | None:
    """Optional maker-checker: X-Force-Live-Approver must differ from X-Actor."""
    if not _force_live_two_person_required():
        return None
    approver = (x_approver or "").strip()
    if not approver:
        raise HTTPException(403, "force_live_approver_required")
    low = approver.lower()
    if low.startswith("scout") or "assist" in low:
        raise HTTPException(403, "force_live_human_only")
    if low == actor.strip().lower():
        raise HTTPException(403, "force_live_approver_must_differ")
    return approver[:256]


class ForceLiveBody(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


def _require_rule_governance(x_rule_governance_secret: str | None) -> None:
    """N2: when RULE_GOVERNANCE_SECRET is set, mutating rule APIs require X-Rule-Governance-Secret."""
    expected = settings.rule_governance_secret
    if not expected:
        return
    got = (x_rule_governance_secret or "").strip()
    if not got or got != expected:
        raise HTTPException(
            403,
            "rule governance secret required (set RULE_GOVERNANCE_SECRET on server; send X-Rule-Governance-Secret)",
        )


@router.get("/telemetry")
async def rule_hit_telemetry():
    """N3/N4: per-rule hit counts (Redis when available, else process memory) + /metrics."""
    return get_rule_hit_telemetry()


@router.get("/change-log")
async def get_rule_change_log(
    limit: int = Query(default=100, ge=1, le=2000),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
):
    """Recent rule pack mutations (append-only JSONL under rules_path)."""
    _ = _actor_from_headers(x_actor)
    p = _change_log_path()
    if not p.is_file():
        return {"items": [], "path": str(p)}
    lines = p.read_text(encoding="utf-8").splitlines()
    tail = lines[-limit:] if len(lines) > limit else lines
    items: list[dict[str, Any]] = []
    for line in reversed(tail):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"items": items, "path": str(p), "count": len(items)}


@router.get("")
async def list_rule_packs():
    return {"packs": _read_all_packs()}


@router.get("/vertical-packs")
async def list_vertical_pack_catalog():
    return {"vertical_packs": list_vertical_packs()}


def _install_vertical_pack_core(
    vertical_name: str,
    *,
    overwrite: bool,
) -> dict[str, Any]:
    pack = get_vertical_pack(vertical_name)
    if not pack:
        raise HTTPException(404, f"unknown vertical pack '{vertical_name}'")
    vertical_id = _slugify_pack_name(vertical_name)
    existing_path: Path | None = None
    existing_file = ""
    for name, path in _list_pack_paths().items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if str(data.get("__vertical_id", "")) == vertical_id:
            existing_path = path
            existing_file = name
            break
    if existing_path and not overwrite:
        raise HTTPException(
            409,
            f"pack '{existing_file}' already exists; pass overwrite=true to replace",
        )
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    payload = dict(pack)
    payload["__vertical_id"] = vertical_id
    fpath = existing_path or _new_pack_path("vertical")
    fpath.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    load_rules()
    return {
        "installed": fpath.name,
        "vertical": vertical_name.lower(),
        "rules": len(pack.get("rules", [])),
        "pack": pack,
    }


def _kill_gate_for_vertical(
    vertical_name: str, body: PromoteVerticalPackBody
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (pack, gate). Raises 404 if unknown; caller enforces promote_allowed."""
    pack = get_vertical_pack(vertical_name)
    if not pack:
        raise HTTPException(404, f"unknown vertical pack '{vertical_name}'")
    metrics: dict[str, Any] = {
        "precision": body.precision,
        "recall": body.recall,
        "f1_score": body.f1_score,
    }
    if body.false_positive_rate is not None:
        metrics["false_positive_rate"] = body.false_positive_rate
    gate = evaluate_kill_criteria(
        metrics,
        pack.get("kill_criteria"),
        events_evaluated=body.events_evaluated,
    )
    gate = {**gate, "metrics": metrics}
    return pack, gate


async def _backtest_gate_for_vertical(
    vertical_name: str,
    body: PromoteVerticalPackBody,
    session: AsyncSession,
) -> dict[str, Any]:
    pack = get_vertical_pack(vertical_name)
    if not pack:
        raise HTTPException(404, f"unknown vertical pack '{vertical_name}'")
    jid = (body.backtest_job_id or "").strip()
    require = bool(settings.require_backtest_before_promote)
    if not jid:
        return backtest_before_promote_gate(
            job_status=None,
            metrics_json=None,
            kill_criteria=pack.get("kill_criteria"),
            require_job=require,
            job_id=None,
        )
    try:
        uid = uuid.UUID(jid)
    except ValueError as exc:
        raise HTTPException(400, detail="invalid backtest_job_id") from exc
    job = await session.get(BacktestRun, uid)
    if job is None:
        raise HTTPException(404, detail="backtest job not found")
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    return backtest_before_promote_gate(
        job_status=status,
        metrics_json=job.metrics_json if isinstance(job.metrics_json, dict) else None,
        kill_criteria=pack.get("kill_criteria"),
        require_job=True,
        job_id=str(job.id),
    )


@router.get("/backtest-before-promote-posture")
async def backtest_before_promote_posture(
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Ops: whether warehouse backtest is required before vertical pack install/promote."""
    return {
        "schema_id": "tarka.backtest_before_promote_posture/v1",
        "require_backtest_before_promote": bool(
            settings.require_backtest_before_promote
        ),
        "enqueue": "POST /v1/rules/backtest/jobs",
        "job_status": "GET /v1/rules/backtest/jobs/{job_id}",
        "promote_body_field": "backtest_job_id",
        "ui": "/ops/backtest",
        "note": (
            "Marble-style: bind succeeded warehouse backtest metrics to kill_criteria "
            "before install/promote. Simulation metrics alone remain allowed when require=false "
            "and backtest_job_id is omitted."
        ),
    }


@router.post("/vertical-packs/{vertical_name}/install", status_code=201)
async def install_vertical_pack(
    vertical_name: str,
    body: PromoteVerticalPackBody,
    overwrite: bool = False,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    """Install pack only when kill_criteria pass (same bar as promote — S5)."""
    _require_rule_governance(x_rule_governance_secret)
    _pack, gate = _kill_gate_for_vertical(vertical_name, body)
    bt_gate = await _backtest_gate_for_vertical(vertical_name, body, session)
    if not gate["promote_allowed"]:
        raise HTTPException(
            409,
            detail={
                "blockers": gate["blockers"],
                "promote_gate": gate,
                "backtest_promote_gate": bt_gate,
            },
        )
    if not bt_gate.get("promote_allowed"):
        raise HTTPException(
            409,
            detail={
                "blockers": bt_gate.get("blockers") or ["backtest_before_promote"],
                "promote_gate": {k: v for k, v in gate.items() if k != "metrics"},
                "backtest_promote_gate": bt_gate,
            },
        )
    result = _install_vertical_pack_core(
        vertical_name,
        overwrite=overwrite,
    )
    _append_rule_change(
        "install_vertical",
        result["installed"],
        actor=_actor_from_headers(x_actor),
        detail={
            "vertical": vertical_name.lower(),
            "overwrite": overwrite,
            "events_evaluated": body.events_evaluated,
            "metrics": gate.get("metrics"),
            "promote_gate": {k: v for k, v in gate.items() if k != "metrics"},
            "backtest_promote_gate": bt_gate,
        },
    )
    return {
        "installed": result["installed"],
        "vertical": result["vertical"],
        "rules": result["rules"],
        "promote_gate": {k: v for k, v in gate.items() if k != "metrics"},
        "backtest_promote_gate": bt_gate,
    }


@router.post("/vertical-packs/{vertical_name}/promote", status_code=201)
async def promote_vertical_pack(
    vertical_name: str,
    body: PromoteVerticalPackBody,
    overwrite: bool = False,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    _pack, gate = _kill_gate_for_vertical(vertical_name, body)
    bt_gate = await _backtest_gate_for_vertical(vertical_name, body, session)
    if not gate["promote_allowed"]:
        raise HTTPException(
            409,
            detail={
                "blockers": gate["blockers"],
                "promote_gate": gate,
                "backtest_promote_gate": bt_gate,
            },
        )
    if not bt_gate.get("promote_allowed"):
        raise HTTPException(
            409,
            detail={
                "blockers": bt_gate.get("blockers") or ["backtest_before_promote"],
                "promote_gate": {k: v for k, v in gate.items() if k != "metrics"},
                "backtest_promote_gate": bt_gate,
            },
        )
    actor = _actor_from_headers(x_actor)
    metrics = gate.get("metrics") or {}
    result = _install_vertical_pack_core(
        vertical_name,
        overwrite=overwrite,
    )
    gate_public = {k: v for k, v in gate.items() if k != "metrics"}
    _append_rule_change(
        "promote_vertical",
        result["installed"],
        actor=actor,
        detail={
            "vertical": vertical_name.lower(),
            "overwrite": overwrite,
            "events_evaluated": body.events_evaluated,
            "metrics": metrics,
            "promote_gate": gate_public,
            "backtest_promote_gate": bt_gate,
        },
    )
    return {
        "installed": result["installed"],
        "vertical": result["vertical"],
        "rules": result["rules"],
        "promoted": True,
        "promote_gate": gate_public,
        "backtest_promote_gate": bt_gate,
    }


class ShadowAutoPromoteProvisionIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    auto_promote: bool
    leftover_add_cap: int
    leftover_fp_rate_cap: float
    min_labeled_extras: int


@router.get("/shadow-auto-promote-provision")
async def get_shadow_auto_promote_provision(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    return load_provision(tenant_id)


@router.put("/shadow-auto-promote-provision")
async def put_shadow_auto_promote_provision(
    body: ShadowAutoPromoteProvisionIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    actor = (x_actor or "").strip() or str(getattr(user, "user_id", "") or "")
    if not actor:
        actor = "api"
    try:
        return save_provision(
            body.tenant_id,
            auto_promote=body.auto_promote,
            leftover_add_cap=body.leftover_add_cap,
            leftover_fp_rate_cap=body.leftover_fp_rate_cap,
            min_labeled_extras=body.min_labeled_extras,
            provisioned_by=actor[:256],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/shadow-packs/auto-promote-tick")
async def auto_promote_tick(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    out = await maybe_auto_promote_shadow(tenant_id)
    parked = await maybe_park_live_rule_slip(tenant_id)
    out["live_rule_slip_parked"] = parked
    try:
        from decision_api.brain_wire import maybe_kill_leftover_fp_shadows

        await maybe_kill_leftover_fp_shadows(tenant_id)
    except Exception:
        logger.exception("maybe_kill_leftover_fp_shadows failed tenant=%s", tenant_id)
    return out


@router.post("/shadow-packs/{draft_id}/promote")
async def promote_shadow_pack(
    draft_id: str,
    tenant_id: str = Query(..., min_length=1, max_length=128),
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _user=Depends(require_role("analyst")),
):
    from decision_api.json_rules import get_shadow_packs
    from decision_api.leftover_promote_gate import compute_desk_and_leftover_gates

    want = (draft_id or "").strip()
    match = next(
        (p for p in get_shadow_packs() if str(p.get("name") or "") == want),
        None,
    )
    if match is None:
        raise HTTPException(404, "no_shadow_draft")
    gates = await compute_desk_and_leftover_gates(tenant_id, want, session=session)
    leftover_g = gates["leftover_promote_gate"]
    desk = gates["desk_promote_gate"]
    leftover_blockers = leftover_g.get("blockers") or []
    desk_blockers = desk.get("blockers") or []
    if leftover_blockers or desk_blockers or not desk.get("promote_allowed"):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "promote_blocked",
                "desk_promote_gate": desk,
                "leftover_promote_gate": leftover_g,
            },
        )
    return activate_shadow_pack(
        want,
        actor=_actor_from_headers(x_actor),
        reason="promote_shadow_pack",
    )


@router.post("/{filename}/force-live")
async def force_live_pack(
    filename: str,
    body: ForceLiveBody,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_force_live_approver: str | None = Header(
        default=None, alias="X-Force-Live-Approver"
    ),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    """Skip leftover + science. Human actor + reason only. Scout / assist 403.

    When ``RULE_FORCE_LIVE_TWO_PERSON`` is on, require ``X-Force-Live-Approver``
    distinct from the actor (stretch maker-checker).
    """
    _require_rule_governance(x_rule_governance_secret)
    actor = _require_force_live_human(x_actor)
    approver = _require_force_live_approver(actor, x_force_live_approver)
    fpath = _existing_pack_path(filename)
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    prior_mode = str(pack.get("mode") or "active")
    pack["mode"] = "active"
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    detail: dict = {
        "actor": actor,
        "reason": body.reason,
        "file": filename,
        "prior_mode": prior_mode,
    }
    if approver is not None:
        detail["approver"] = approver
    _append_rule_change(
        "rule_force_live",
        filename,
        actor=actor,
        detail=detail,
    )
    out: dict = {"mode": "active", "forced": True, "file": filename}
    if approver is not None:
        out["approver"] = approver
    return out


@router.get("/{filename}")
async def get_rule_pack(filename: str):
    fpath = _existing_pack_path(filename)
    data = json.loads(fpath.read_text(encoding="utf-8"))
    data["_file"] = fpath.name
    return data


@router.post("", status_code=201)
async def create_rule_pack(
    body: RulePackIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    slug = _slugify_pack_name(body.name)
    for path in _list_pack_paths().values():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        existing_name = str(data.get("name", "")).strip().lower().replace(" ", "_")
        if existing_name == slug:
            raise HTTPException(409, f"pack name '{body.name}' already exists")
    pack = {
        "version": 1,
        "name": body.name,
        "mode": "shadow",
        "rules": [_rule_to_dict(r) for r in body.rules],
        "tag_rules": [_tag_rule_to_dict(r) for r in body.tag_rules],
        "canary_percent": body.canary_percent,
        "effective_at": body.effective_at,
        "approved_by": body.approved_by,
    }
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath = _new_pack_path("pack")
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "create",
        fpath.name,
        actor=_actor_from_headers(x_actor),
        detail={"name": body.name},
    )
    return {"file": fpath.name, "pack": pack}


@router.put("/{filename}")
async def update_rule_pack(
    filename: str,
    body: RulePackIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    fpath = _existing_pack_path(filename)
    pack = {
        "version": 1,
        "name": body.name,
        "mode": "shadow",
        "rules": [_rule_to_dict(r) for r in body.rules],
        "tag_rules": [_tag_rule_to_dict(r) for r in body.tag_rules],
        "canary_percent": body.canary_percent,
        "effective_at": body.effective_at,
        "approved_by": body.approved_by,
    }
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "update",
        filename,
        actor=_actor_from_headers(x_actor),
        detail={"name": body.name, "rule_count": len(pack.get("rules", []))},
    )
    return {"file": filename, "pack": pack}


@router.delete("/{filename}")
async def delete_rule_pack(
    filename: str,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    fpath = _existing_pack_path(filename)
    fpath.unlink()
    load_rules()
    _append_rule_change("delete", filename, actor=_actor_from_headers(x_actor))
    return {"deleted": filename}


@router.post("/{filename}/rules")
async def add_rule(
    filename: str,
    body: RuleIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    fpath = _existing_pack_path(filename)
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    if not body.id:
        body.id = f"rule_{uuid.uuid4().hex[:8]}"
    pack.setdefault("rules", []).append(_rule_to_dict(body))
    pack["mode"] = "shadow"
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "add_rule",
        filename,
        actor=_actor_from_headers(x_actor),
        detail={"rule_id": body.id},
    )
    return {"added": body.id}


class ScoutPackIn(BaseModel):
    """A scout-authored shadow pack created by the AI scout agent."""

    name: str = Field(min_length=1, max_length=256)
    mode: str = Field(default="shadow")
    rules: list[dict[str, Any]] = Field(default_factory=list)
    tag_rules: list[dict[str, Any]] = Field(default_factory=list)
    authored_by: str = Field(default="scout_coordinated_burst", max_length=128)
    is_ai_authored: bool = Field(default=True)
    scout_report_id: str = Field(default="", max_length=128)
    tenant_id: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


# ponytail: mirrors pack_author_contract.validate_ai_authored_pack
# from shadow_agent, kept inline so decision-api stays self-contained.
_AI_PACK_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "event_type",
        "entity_id",
        "session_id",
        "acc_id",
        "user_id",
        "device_fingerprint",
        "canvas_hash",
        "webgl_vendor",
        "user_agent",
        "screen_resolution",
        "timezone_offset",
        "language",
        "platform",
        "vendor",
        "tx_count_1h",
        "tx_count_24h",
        "tx_amount_1h",
        "tx_amount_24h",
        "distinct_devices_24h",
        "distinct_ips_24h",
        "vendor_fingerprint_score",
        "vendor_incognia_risk",
        "ip_address",
        "ip_risk_score",
        "geo_country",
        "geo_city",
        "amount",
        "currency",
    }
)
_AI_PACK_ALLOWED_OPS: frozenset[str] = frozenset(
    {
        "eq",
        "not_eq",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        "exists",
        "not_exists",
        "is_true",
        "is_false",
    }
)
_AI_PACK_SCORE_DELTA_MIN = 5.0
_AI_PACK_SCORE_DELTA_MAX = 30.0


def _validate_ai_authored_pack(pack: dict[str, Any]) -> list[str]:
    """Enforce the AI pack-author contract on a scout pack."""
    errors: list[str] = []
    if pack.get("mode") != "shadow":
        errors.append("mode must be 'shadow'")
    if pack.get("is_ai_authored") is not True:
        errors.append("is_ai_authored must be true")
    rules = pack.get("rules") or []
    if not rules:
        errors.append("rules must not be empty")
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = rule.get("id", "unknown")
        sd = rule.get("score_delta")
        try:
            sd_f = float(sd)
        except (TypeError, ValueError):
            errors.append(f"rule {rid}: score_delta is not a number")
            continue
        if sd_f < _AI_PACK_SCORE_DELTA_MIN or sd_f > _AI_PACK_SCORE_DELTA_MAX:
            errors.append(
                f"rule {rid}: score_delta {sd_f} outside [{_AI_PACK_SCORE_DELTA_MIN}, {_AI_PACK_SCORE_DELTA_MAX}]"
            )
        for cond in rule.get("when") or []:
            if not isinstance(cond, dict):
                continue
            field = cond.get("field", "")
            op = cond.get("op", "eq")
            if field and field not in _AI_PACK_ALLOWED_FIELDS:
                errors.append(f"rule {rid}: unknown field '{field}'")
            if op not in _AI_PACK_ALLOWED_OPS:
                errors.append(f"rule {rid}: disallowed op '{op}'")
    return errors


async def _scout_leftover_verdict(tid: str, pack: dict[str, Any]) -> dict[str, Any]:
    from decision_api.brain_wire import brain_wire_verdict
    from decision_api.db import SessionLocal
    from decision_api.leftover_promote_gate import compute_desk_and_leftover_gates

    async with SessionLocal() as session:
        gates = await compute_desk_and_leftover_gates(tid, None, session=session)
    leftover_g = gates.get("leftover_promote_gate") if isinstance(gates, dict) else {}
    leftover_g = leftover_g if isinstance(leftover_g, dict) else {}
    helpfulness = leftover_g.get("helpfulness")
    if not isinstance(helpfulness, dict):
        helpfulness = leftover_g
    precision = (
        gates.get("rule_precision_after_labels") if isinstance(gates, dict) else {}
    )
    try:
        fp_cap = float(helpfulness.get("fp_rate_cap") or 0.4)
    except (TypeError, ValueError):
        fp_cap = 0.4
    ids = [
        str(r.get("id") or "").strip()
        for r in (pack.get("rules") or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    ]
    verdict = brain_wire_verdict(
        helpfulness, precision, proposed_rule_ids=ids, fp_cap=fp_cap
    )
    verdict["_helpfulness"] = dict(helpfulness)
    return verdict


@router.post("/scout-pack", status_code=201)
async def create_scout_pack(
    body: ScoutPackIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    """Persist a scout-suggested rule pack in Observe (shadow) mode.

    The pack is written with ``mode=shadow`` so the Observe page lists it and
    shadow evaluation covers it.  It never affects live decisions until an
    analyst promotes it through the existing governance gates.
    """
    _require_rule_governance(x_rule_governance_secret)
    if body.mode != "shadow":
        raise HTTPException(400, "scout packs must use mode='shadow'")
    from decision_api.json_rules import get_shadow_packs
    from decision_api.live_rule_slip import slip_draft_would_clobber

    if slip_draft_would_clobber(body.name, None, get_shadow_packs()):
        raise HTTPException(409, "slip_draft_exists")
    pack: dict[str, Any] = {
        "version": 1,
        "name": body.name,
        "mode": "shadow",
        "rules": body.rules,
        "tag_rules": body.tag_rules,
        "canary_percent": None,
        "effective_at": None,
        "approved_by": None,
        "authored_by": body.authored_by,
        "is_ai_authored": body.is_ai_authored,
        "scout_report_id": body.scout_report_id,
        "evidence": dict(body.evidence) if isinstance(body.evidence, dict) else {},
    }
    tid = (body.tenant_id or "").strip()
    if not tid:
        raise HTTPException(409, "leftover_helpfulness_no_tenant")
    pack["tenant_id"] = tid
    from decision_api.brain_wire import fingerprint_from_pack, load_killed_fingerprints

    fp = fingerprint_from_pack(pack)
    if fp and fp in load_killed_fingerprints(tid):
        raise HTTPException(409, "leftover_helpfulness_killed")
    ai_errors = _validate_ai_authored_pack(pack)
    if ai_errors:
        raise HTTPException(
            422,
            detail={"validation_errors": ai_errors, "contract": "ai_authored_pack"},
        )
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    verdict = await _scout_leftover_verdict(tid, pack)
    if not verdict.get("publish_allowed"):
        raise HTTPException(
            409, str(verdict.get("reason") or "leftover_helpfulness_refused")
        )
    keep = {str(x) for x in (verdict.get("keep_rule_ids") or [])}
    proposed = [
        r
        for r in (pack.get("rules") or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    ]
    if proposed:
        pack["rules"] = [r for r in proposed if str(r.get("id") or "").strip() in keep]
        body.rules = pack["rules"]
        if not pack["rules"]:
            raise HTTPException(409, str(verdict.get("reason") or "rule_fp_over_cap"))
    if verdict.get("stamp_underpowered"):
        h = (
            verdict.get("_helpfulness")
            if isinstance(verdict.get("_helpfulness"), dict)
            else {}
        )
        ev = pack.get("evidence")
        if not isinstance(ev, dict):
            ev = {}
            pack["evidence"] = ev
        ev["leftover_helpfulness"] = {
            "labeled_extras": h.get("labeled_extras"),
            "extra_tp": h.get("extra_tp"),
            "extra_fp": h.get("extra_fp"),
            "hint": "helpfulness_underpowered",
        }
    fpath = _new_pack_path("scout")
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    actor = _actor_from_headers(x_actor) if x_actor else body.authored_by
    _append_rule_change(
        "create_scout_pack",
        fpath.name,
        actor=actor,
        detail={
            "name": body.name,
            "authored_by": body.authored_by,
            "is_ai_authored": body.is_ai_authored,
            "scout_report_id": body.scout_report_id,
            "rule_count": len(body.rules),
        },
    )
    tid = (body.tenant_id or "").strip()
    if tid:
        try:
            from decision_api.brain_wire import maybe_kill_leftover_fp_shadows

            await maybe_auto_promote_shadow(tid)
            await maybe_park_live_rule_slip(tid)
            await maybe_kill_leftover_fp_shadows(tid)
        except Exception:
            logger.exception("maybe_auto_promote_shadow failed tenant=%s", tid)
    return {"file": fpath.name, "pack": pack, "mode": "shadow"}


class RulePackMode(BaseModel):
    mode: str


@router.put("/{filename}/mode")
async def set_pack_mode(
    filename: str,
    body: RulePackMode,
    tenant_id: str | None = Query(None),  # kept: clients still send leftover-era query
    session: AsyncSession = Depends(
        get_session
    ),  # kept: signature stable after leftover floor moved to Promote
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    """Set a rule pack to active, shadow, or disabled mode."""
    fpath = _existing_pack_path(filename)
    if body.mode not in ("active", "shadow", "disabled"):
        raise HTTPException(400, "mode must be 'active', 'shadow', or 'disabled'")
    if body.mode == "active":
        raise HTTPException(409, "shadow_first")
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    pack["mode"] = body.mode
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "set_mode",
        filename,
        actor=_actor_from_headers(x_actor),
        detail={"mode": body.mode},
    )
    return {"file": filename, "mode": body.mode}


@router.delete("/{filename}/rules/{rule_id}")
async def remove_rule(
    filename: str,
    rule_id: str,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_rule_governance_secret: str | None = Header(
        default=None, alias="X-Rule-Governance-Secret"
    ),
):
    _require_rule_governance(x_rule_governance_secret)
    fpath = _existing_pack_path(filename)
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    original = len(pack.get("rules", []))
    pack["rules"] = [r for r in pack.get("rules", []) if r.get("id") != rule_id]
    if len(pack["rules"]) == original:
        raise HTTPException(404, f"rule '{rule_id}' not found")
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "remove_rule",
        filename,
        actor=_actor_from_headers(x_actor),
        detail={"rule_id": rule_id},
    )
    return {"deleted": rule_id}


@router.post("/shadow/reload")
async def reload_shadow_rules(_admin=Depends(require_role("admin"))):
    load_shadow_rules()
    return {"ok": True}


@router.get("/shadow/observations")
async def shadow_observations(limit: int = 100):
    return {"observations": get_observations(limit)}


@router.get("/shadow/stats")
async def shadow_stats():
    return get_observation_stats()


def _rule_to_dict(r: RuleIn) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id or f"rule_{uuid.uuid4().hex[:8]}",
        "when": [{"field": c.field, "op": c.op, "value": c.value} for c in r.when],
        "tags": r.tags,
        "score_delta": r.score_delta,
        "description": r.description,
    }
    if r.when_ast is not None:
        out["when_ast"] = r.when_ast
    return out


def _tag_rule_to_dict(r: TagRuleIn) -> dict[str, Any]:
    return {
        "id": r.id or f"tagrule_{uuid.uuid4().hex[:8]}",
        "any_tag": r.any_tag,
        "tags": r.tags,
        "score_delta": r.score_delta,
        "description": r.description,
    }
