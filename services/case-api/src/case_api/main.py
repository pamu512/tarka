import asyncio
import hashlib
import hmac
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.builtin_playbooks import PLAYBOOKS
from case_api.config import settings
from case_api.db import Base, get_session, init_db
from case_api.dispute_api import router as dispute_router
from case_api.investigation_label_drafts_api import router as investigation_label_drafts_router
from case_api.investigation_templates_api import router as investigation_templates_router
from case_api.models import Case, CaseComment, CaseView, SARFiling
from case_api.ops_kpi_series import router as ops_kpi_series_router
from case_api.retention import DEFAULT_RETENTION_DAYS, retention_loop
from case_api.sar import SARGenerator
from case_api.schemas import CaseOut, CommentIn, CreateCaseRequest, LabelsIn
from case_api.template_apply import (
    apply_case_payload_to_case,
    apply_investigation_template_transaction,
    resolve_playbook_or_template,
)
from case_api.workflow import evaluate_workflows, get_workflows, is_sla_breached, load_workflows

_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from audit_trail import AuditTrail, create_audit_model  # noqa: E402
from auth_rbac import get_current_user, require_role, setup_auth  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402
from rate_limiter import setup_rate_limiter  # noqa: E402
from webhook_sender import WebhookSender  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

AuditRecord = create_audit_model(Base)
_trail = AuditTrail(AuditRecord)

# ---------- websocket connections for live feed ----------
_ws_clients: set[WebSocket] = set()
_PRIORITY_WEIGHT = {"critical": 100, "high": 70, "medium": 40, "low": 15}
_STATUS_WEIGHT = {"open": 25, "investigating": 20, "resolved": -10, "closed": -30}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _bundle_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _hash_chain(records: list[dict[str, Any]]) -> str:
    current = ""
    for item in records:
        current = hashlib.sha256(f"{current}:{_canonical_json(item)}".encode("utf-8")).hexdigest()
    return current


def _bundle_signature(payload: dict[str, Any]) -> str:
    key = (settings.evidence_signing_secret or "tarka-evidence-dev-secret").encode("utf-8")
    return hmac.new(key, _canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


def _signing_key_id() -> str:
    key = settings.evidence_signing_secret or "tarka-evidence-dev-secret"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _queue_score(case: Case) -> float:
    p = _PRIORITY_WEIGHT.get((case.priority or "medium").lower(), 30)
    s = _STATUS_WEIGHT.get((case.status or "open").lower(), 0)
    label_boost = 0
    labels = set(case.labels or [])
    if "confirmed_fraud" in labels:
        label_boost += 25
    if "chargeback" in labels or "dispute:chargeback" in labels:
        label_boost += 15
    return float(p + s + label_boost)


def _recommended_action(case: Case, score: float) -> str:
    if (case.priority or "").lower() == "critical" or score >= 120:
        return "immediate_triage"
    if score >= 85:
        return "investigate_now"
    if score >= 55:
        return "queue_review"
    return "monitor"


def _apply_case_mutations(case: Case, payload: dict[str, Any]) -> None:
    apply_case_payload_to_case(case, payload)


class BulkCaseUpdateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, description="Only cases in this tenant may be updated")
    case_ids: list[uuid.UUID] = Field(default_factory=list)
    status: str | None = None
    priority: str | None = None
    assigned_team: str | None = None
    add_labels: list[str] = Field(default_factory=list)


class SaveViewRequest(BaseModel):
    tenant_id: str
    name: str = Field(min_length=1, max_length=128)
    filters: dict[str, Any] = Field(default_factory=dict)


def _view_to_payload(v: CaseView) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "name": v.name,
        "tenant_id": v.tenant_id,
        "filters": v.filters or {},
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


class EvidenceVerifyRequest(BaseModel):
    bundle: dict[str, Any]


async def _broadcast(event: dict):
    import json

    data = json.dumps(event, default=str)
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    application.state.http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    application.state.webhook = WebhookSender(max_retries=5, http=application.state.http)
    load_workflows(os.environ.get("WORKFLOWS_PATH", "./workflows"))

    retention_task = None
    if DEFAULT_RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(retention_loop())

    yield

    if retention_task:
        retention_task.cancel()
    await application.state.http.aclose()


app = FastAPI(title="Tarka Case API", version="4.0.0", lifespan=lifespan)
setup_observability(app, "case-api")
setup_auth(app)
setup_rate_limiter(app, rpm=int(os.environ.get("RATE_LIMIT_RPM", "600")))
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(dispute_router)
app.include_router(investigation_label_drafts_router)
app.include_router(investigation_templates_router)
app.include_router(ops_kpi_series_router)


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/slo")
async def slo_status():
    m = get_metrics()
    cur = m.request_count_summary()
    return {
        "service": "case-api",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 200,
        "error_budget_window_days": 30,
        "targets_note": "See docs/docs/guides/service-slos-v1.md; current from in-process HTTP counters.",
        "current": cur,
    }


@app.get("/v1/cases", response_model=dict)
async def list_cases(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
    limit: int = 50,
    sort_by: str = "queue",
):
    q = select(Case).where(Case.tenant_id == tenant_id)
    if status:
        q = q.where(Case.status == status)
    if sort_by == "updated":
        q = q.order_by(Case.updated_at.desc())
    elif sort_by == "priority":
        q = q.order_by(Case.priority.asc(), Case.updated_at.desc())
    else:
        q = q.order_by(Case.updated_at.desc())
    q = q.limit(limit)
    result = await session.execute(q)
    rows = result.scalars().all()
    items = [CaseOut.model_validate(r).model_dump() for r in rows]
    if sort_by == "queue":
        enriched: list[dict[str, Any]] = []
        for row, item in zip(rows, items):
            score = _queue_score(row)
            item["queue_score"] = score
            item["recommended_action"] = _recommended_action(row, score)
            enriched.append(item)
        enriched.sort(key=lambda x: float(x.get("queue_score", 0.0)), reverse=True)
        return {"items": enriched}
    return {"items": items}


@app.post("/v1/cases", response_model=CaseOut, status_code=201)
async def create_case(
    body: CreateCaseRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_role("analyst")),
):
    user = get_current_user(request)
    trail_key, apply_cfg, tmpl_uuid = None, {}, None
    if body.playbook_id and str(body.playbook_id).strip():
        trail_key, apply_cfg, tmpl_uuid = await resolve_playbook_or_template(
            session,
            body.tenant_id,
            body.playbook_id,
        )

    c = Case(
        tenant_id=body.tenant_id,
        title=body.title,
        entity_id=body.entity_id,
        trace_id=body.trace_id,
        priority=body.priority,
        status="open",
        labels=[],
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)

    await _trail.record(
        session,
        actor=user.user_id,
        action="create_case",
        resource_type="case",
        resource_id=str(c.id),
        changes={"status": {"old": None, "new": "open"}, "priority": {"old": None, "new": body.priority}},
        tenant_id=body.tenant_id,
    )
    await session.commit()

    if body.playbook_id and str(body.playbook_id).strip():
        await apply_investigation_template_transaction(
            trail=_trail,
            session=session,
            case=c,
            apply_config=apply_cfg,
            trail_key=trail_key or "",
            actor=user.user_id,
            trail_action="apply_playbook_on_create",
            tenant_id=body.tenant_id,
            template_uuid=tmpl_uuid,
        )
        await session.refresh(c)

    case_dict = CaseOut.model_validate(c).model_dump(mode="json")
    http = request.app.state.http
    ctx = await evaluate_workflows("case_created", case_dict, http=http)
    if ctx.mutations:
        old_state = CaseOut.model_validate(c).model_dump(mode="json")
        if "priority" in ctx.mutations:
            c.priority = ctx.mutations["priority"]
        if "status" in ctx.mutations:
            c.status = ctx.mutations["status"]
        if "labels" in ctx.mutations:
            c.labels = ctx.mutations["labels"]
        if "assigned_team" in ctx.mutations:
            c.assigned_team = ctx.mutations["assigned_team"]
        for comment in ctx.mutations.get("_comments", []):
            session.add(CaseComment(case_id=c.id, author=comment["author"], body=comment["body"]))
        await session.commit()
        await session.refresh(c)

        new_state = CaseOut.model_validate(c).model_dump(mode="json")
        diff = _trail.diff(old_state, new_state)
        if diff:
            await _trail.record(
                session,
                actor="workflow-engine",
                action="workflow_mutation",
                resource_type="case",
                resource_id=str(c.id),
                changes=diff,
                tenant_id=body.tenant_id,
            )
            await session.commit()

    await _broadcast({"event": "case_created", "case": CaseOut.model_validate(c).model_dump(mode="json")})
    return CaseOut.model_validate(c)


async def _case_for_tenant(session: AsyncSession, case_id: uuid.UUID, tenant_id: str) -> Case:
    result = await session.execute(select(Case).where(Case.id == case_id, Case.tenant_id == tenant_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "not found")
    return row


@app.get("/v1/cases/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope; must match the case's tenant_id"),
    session: AsyncSession = Depends(get_session),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    return CaseOut.model_validate(case)


@app.get("/v1/cases/{case_id}/evidence-bundle")
async def get_case_evidence_bundle(
    case_id: uuid.UUID,
    request: Request,
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    session: AsyncSession = Depends(get_session),
):
    """Procurement / audit: case row + linked fraud decision audit (inference_context, recommended_action)."""
    case = await _case_for_tenant(session, case_id, tenant_id)
    http: httpx.AsyncClient = request.app.state.http
    base = settings.decision_api_url.rstrip("/")
    trace = str(case.trace_id).strip()
    decision_block: dict[str, Any] = {}
    if trace and base:
        try:
            r = await http.get(f"{base}/v1/audit/{trace}", timeout=8.0)
            if r.status_code == 200:
                decision_block = r.json()
        except Exception:
            decision_block = {"error": "decision_api_unreachable"}

    case_payload = CaseOut.model_validate(case).model_dump(mode="json")
    # Evidence bundle v1 alignment (OSS #50): schema_id + provenance + content hash.
    bundle_core: dict[str, Any] = {
        "schema_id": "tarka.evidence_bundle/v1",
        "contract_version": "oss-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "turn_id": f"case:{case.id}",
        "prompt_version": "case-api/v1",
        "playbook_id": None,
        "redaction_level": "export_safe",
        "tool_invocation_count": 0,
        "narrative": {
            "reply": "",
        },
        "tool_trace_redacted": [],
    }
    # Deterministic content hash over stable subset for procurement exports.
    content_basis = {
        "tenant_id": tenant_id,
        "case": case_payload,
        "decision_audit": decision_block,
    }
    bundle_core["content_sha256"] = hashlib.sha256(_canonical_json(content_basis).encode("utf-8")).hexdigest()

    bundle = {
        "tenant_id": tenant_id,
        "case": case_payload,
        "decision_audit": decision_block,
        "evidence_bundle_v1": bundle_core,
        "signing_key_id": _signing_key_id(),
    }
    bundle["bundle_signature"] = _bundle_signature(bundle)
    return bundle


@app.patch("/v1/cases/{case_id}")
async def update_case(
    case_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    _=Depends(require_role("analyst")),
):
    user = get_current_user(request)
    case = await _case_for_tenant(session, case_id, tenant_id)

    body = await request.json()
    old_state = CaseOut.model_validate(case).model_dump(mode="json")

    for field in ("status", "priority", "assigned_team", "title"):
        if field in body:
            setattr(case, field, body[field])

    await session.commit()
    await session.refresh(case)
    new_state = CaseOut.model_validate(case).model_dump(mode="json")

    diff = _trail.diff(old_state, new_state)
    if diff:
        await _trail.record(
            session,
            actor=user.user_id,
            action="update_case",
            resource_type="case",
            resource_id=str(case_id),
            changes=diff,
            tenant_id=case.tenant_id,
        )
        await session.commit()

    await _broadcast({"event": "case_updated", "case": new_state})
    return CaseOut.model_validate(case)


@app.post("/v1/cases/{case_id}/comments", status_code=201)
async def add_comment(
    case_id: uuid.UUID,
    body: CommentIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    _=Depends(require_role("analyst")),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    session.add(CaseComment(case_id=case_id, author=body.author, body=body.body))
    await session.commit()

    user = get_current_user(request)
    await _trail.record(
        session,
        actor=user.user_id,
        action="add_comment",
        resource_type="case",
        resource_id=str(case_id),
        changes={"comment": {"author": body.author, "body": body.body[:200]}},
        tenant_id=case.tenant_id,
    )
    await session.commit()
    return {"ok": True}


@app.post("/v1/cases/{case_id}/labels")
async def apply_labels(
    case_id: uuid.UUID,
    body: LabelsIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    _=Depends(require_role("analyst")),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    old_labels = list(case.labels) if case.labels else []
    case.labels = sorted(set(old_labels) | set(body.labels))
    await session.commit()

    user = get_current_user(request)
    await _trail.record(
        session,
        actor=user.user_id,
        action="update_labels",
        resource_type="case",
        resource_id=str(case_id),
        changes={"labels": {"old": old_labels, "new": case.labels}},
        tenant_id=case.tenant_id,
    )
    await session.commit()
    return {"ok": True, "labels": case.labels}


@app.post("/v1/cases/bulk-update")
async def bulk_update_cases(
    body: BulkCaseUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_role("analyst")),
):
    if not body.case_ids:
        return {"updated": 0, "items": []}
    user = get_current_user(request)
    q = select(Case).where(Case.id.in_(body.case_ids), Case.tenant_id == body.tenant_id)
    result = await session.execute(q)
    rows = result.scalars().all()
    updated: list[dict[str, Any]] = []
    for case in rows:
        old_state = CaseOut.model_validate(case).model_dump(mode="json")
        payload = {
            "status": body.status,
            "priority": body.priority,
            "assigned_team": body.assigned_team,
            "labels": body.add_labels,
        }
        _apply_case_mutations(case, payload)
        new_state = CaseOut.model_validate(case).model_dump(mode="json")
        diff = _trail.diff(old_state, new_state)
        if diff:
            await _trail.record(
                session,
                actor=user.user_id,
                action="bulk_update_case",
                resource_type="case",
                resource_id=str(case.id),
                changes=diff,
                tenant_id=case.tenant_id,
            )
        updated.append(new_state)
    await session.commit()
    await _broadcast({"event": "cases_bulk_updated", "count": len(updated)})
    return {"updated": len(updated), "items": updated}


@app.post("/v1/cases/{case_id}/playbooks/{playbook_id}")
async def apply_playbook(
    case_id: uuid.UUID,
    playbook_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    _=Depends(require_role("analyst")),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    user = get_current_user(request)
    trail_key, apply_cfg, tmpl_uuid = await resolve_playbook_or_template(session, tenant_id, playbook_id)
    await apply_investigation_template_transaction(
        trail=_trail,
        session=session,
        case=case,
        apply_config=apply_cfg,
        trail_key=trail_key or playbook_id,
        actor=user.user_id,
        trail_action="apply_playbook",
        tenant_id=case.tenant_id,
        template_uuid=tmpl_uuid,
    )
    await session.refresh(case)
    new_state = CaseOut.model_validate(case).model_dump(mode="json")
    await _broadcast({"event": "case_updated", "case": new_state})
    return {"ok": True, "playbook": playbook_id, "case": new_state}


@app.get("/v1/cases/playbooks")
async def list_playbooks():
    return {"playbooks": PLAYBOOKS}


@app.get("/v1/cases/ops/kpis")
async def case_ops_kpis(tenant_id: str, session: AsyncSession = Depends(get_session)):
    """Queue health KPIs for the full case population (aggregated; not capped)."""
    total = (await session.execute(select(func.count()).select_from(Case).where(Case.tenant_id == tenant_id))).scalar_one()
    if total == 0:
        return {
            "tenant_id": tenant_id,
            "total_cases": 0,
            "queue_score_avg": 0.0,
            "critical_open": 0,
            "investigating_rate": 0.0,
            "resolved_rate": 0.0,
            "median_case_age_hours": 0.0,
            "by_status": {},
            "sla_breached_open_or_investigating": 0,
            "label_boost_cases": 0,
        }

    st_rows = (
        await session.execute(
            select(Case.status, func.count()).where(Case.tenant_id == tenant_id).group_by(Case.status),
        )
    ).all()
    by_status: dict[str, int] = {}
    for st, ct in st_rows:
        key = (st or "unknown").lower()
        by_status[key] = by_status.get(key, 0) + int(ct)

    investigating = int(by_status.get("investigating", 0))
    resolved = int(by_status.get("resolved", 0) + by_status.get("closed", 0))

    crit_open_q = (
        select(func.count())
        .select_from(Case)
        .where(
            Case.tenant_id == tenant_id,
            func.lower(Case.priority) == "critical",
            func.lower(Case.status).in_(("open", "investigating")),
        )
    )
    critical_open = int((await session.execute(crit_open_q)).scalar_one())

    now = datetime.now(timezone.utc)
    times = (await session.execute(select(Case.created_at).where(Case.tenant_id == tenant_id).where(Case.created_at.is_not(None)))).scalars().all()
    ages: list[float] = []
    for t in times:
        if t:
            ages.append(max(0.0, (now - t).total_seconds() / 3600.0))
    ages.sort()
    median_age = ages[len(ages) // 2] if ages else 0.0

    lean = (
        await session.execute(
            select(Case.priority, Case.status, Case.labels, Case.created_at, Case.sla_hours_override).where(
                Case.tenant_id == tenant_id,
            ),
        )
    ).all()
    queue_scores: list[float] = []
    sla_breached = 0
    label_boost_cases = 0
    for pr, st, labels, ca, slo in lean:
        lbls = set(labels or [])
        if "confirmed_fraud" in lbls or "chargeback" in lbls or "dispute:chargeback" in lbls:
            label_boost_cases += 1
        pseudo = Case()
        pseudo.priority = pr or "medium"
        pseudo.status = st or "open"
        pseudo.labels = list(labels or [])
        queue_scores.append(_queue_score(pseudo))
        if (
            (st or "open").lower() in ("open", "investigating")
            and ca
            and is_sla_breached(
                pr or "medium",
                ca,
                sla_hours_override=slo,
            )
        ):
            sla_breached += 1

    return {
        "tenant_id": tenant_id,
        "total_cases": int(total),
        "queue_score_avg": round(sum(queue_scores) / len(queue_scores), 2) if queue_scores else 0.0,
        "critical_open": critical_open,
        "investigating_rate": round(investigating / total, 4),
        "resolved_rate": round(resolved / total, 4),
        "median_case_age_hours": round(median_age, 2),
        "by_status": by_status,
        "sla_breached_open_or_investigating": sla_breached,
        "label_boost_cases": label_boost_cases,
    }


@app.get("/v1/cases/analytics/cohort-compare")
async def cohort_compare_cases(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    period_days: int = 7,
):
    """Compare case volume: last *period_days* vs prior window of equal length."""
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=period_days)
    prior_start = now - timedelta(days=2 * period_days)
    q_recent = (
        select(func.count())
        .select_from(Case)
        .where(
            Case.tenant_id == tenant_id,
            Case.created_at >= recent_start,
        )
    )
    q_prior = (
        select(func.count())
        .select_from(Case)
        .where(
            Case.tenant_id == tenant_id,
            Case.created_at >= prior_start,
            Case.created_at < recent_start,
        )
    )
    n_recent = (await session.execute(q_recent)).scalar_one()
    n_prior = (await session.execute(q_prior)).scalar_one()
    delta = float(n_recent - n_prior)
    pct = (delta / n_prior * 100.0) if n_prior else None
    return {
        "tenant_id": tenant_id,
        "period_days": period_days,
        "cases_created_recent": int(n_recent),
        "cases_created_prior": int(n_prior),
        "delta": delta,
        "delta_percent_vs_prior": pct,
    }


@app.get("/v1/cases/ops/desk-activity")
async def case_desk_activity(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    period_days: int = 7,
    limit: int = 50,
):
    """Analyst touch volume from audit trail: status/label/comment updates in the last window."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(period_days, 365)))
    lim = max(1, min(limit, 500))
    q = (
        select(AuditRecord.action, func.count())
        .where(
            AuditRecord.tenant_id == tenant_id,
            AuditRecord.resource_type == "case",
            AuditRecord.created_at >= since,
            AuditRecord.action.in_(
                (
                    "update_case",
                    "bulk_update_case",
                    "apply_playbook",
                    "apply_playbook_on_create",
                    "update_labels",
                    "add_comment",
                    "workflow_mutation",
                ),
            ),
        )
        .group_by(AuditRecord.action)
    )
    rows = (await session.execute(q)).all()
    by_action = {str(a): int(c) for a, c in rows}
    total_actions = sum(by_action.values())

    recent_q = (
        select(AuditRecord)
        .where(
            AuditRecord.tenant_id == tenant_id,
            AuditRecord.resource_type == "case",
            AuditRecord.created_at >= since,
        )
        .order_by(AuditRecord.created_at.desc())
        .limit(lim)
    )
    recent_rows = (await session.execute(recent_q)).scalars().all()
    recent = [
        {
            "id": str(r.id),
            "action": r.action,
            "actor": r.actor,
            "resource_id": r.resource_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_rows
    ]
    return {
        "tenant_id": tenant_id,
        "period_days": period_days,
        "since": since.isoformat(),
        "touch_actions_total": total_actions,
        "by_action": by_action,
        "recent": recent,
    }


@app.get("/v1/case-views")
async def list_case_views(tenant_id: str, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(CaseView).where(CaseView.tenant_id == tenant_id).order_by(CaseView.updated_at.desc(), CaseView.name.asc()),
        )
    ).scalars()
    return {"items": [_view_to_payload(v) for v in rows]}


@app.post("/v1/case-views")
async def save_case_view(body: SaveViewRequest, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            select(CaseView).where(
                CaseView.tenant_id == body.tenant_id,
                CaseView.name == body.name,
            ),
        )
    ).scalar_one_or_none()
    if row is None:
        row = CaseView(tenant_id=body.tenant_id, name=body.name, filters=body.filters)
        session.add(row)
    else:
        row.filters = body.filters
    await session.commit()
    await session.refresh(row)
    return {"ok": True, "view": _view_to_payload(row)}


@app.delete("/v1/case-views/{name}")
async def delete_case_view(name: str, tenant_id: str, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            select(CaseView).where(
                CaseView.tenant_id == tenant_id,
                CaseView.name == name,
            ),
        )
    ).scalar_one_or_none()
    existed = row is not None
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"removed": existed}


@app.get("/v1/cases/{case_id}/graph")
async def case_graph(
    case_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    depth: int = 2,
):
    if not settings.graph_service_url:
        return {"nodes": [], "edges": [], "message": "GRAPH_SERVICE_URL not set"}
    case = await _case_for_tenant(session, case_id, tenant_id)
    base = settings.graph_service_url.rstrip("/")
    http: httpx.AsyncClient = request.app.state.http
    r = await http.get(f"{base}/v1/subgraph", params={"entity_id": case.entity_id, "tenant_id": case.tenant_id, "depth": depth})
    r.raise_for_status()
    return r.json()


@app.get("/v1/cases/{case_id}/decision-explanation")
async def case_decision_explanation(
    case_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
):
    """Resolve graph decision explanation for a case via decision-api audit (trace_id on the case)."""
    case = await _case_for_tenant(session, case_id, tenant_id)
    base = (settings.decision_api_url or "").strip().rstrip("/")
    if not base:
        return {
            "case_id": str(case_id),
            "trace_id": case.trace_id,
            "entity_id": case.entity_id,
            "graph_decision_explanation": None,
            "source": "decision_api_url_unset",
        }
    http: httpx.AsyncClient = request.app.state.http
    headers: dict[str, str] = {}
    key = (settings.decision_api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    url = f"{base}/v1/audit/{case.trace_id}"
    try:
        r = await http.get(url, params={"tenant_id": tenant_id, "detail_level": "analyst"}, headers=headers, timeout=10.0)
    except Exception:
        return {
            "case_id": str(case_id),
            "trace_id": case.trace_id,
            "entity_id": case.entity_id,
            "graph_decision_explanation": None,
            "source": "decision_api_unreachable",
        }
    if r.status_code != 200:
        return {
            "case_id": str(case_id),
            "trace_id": case.trace_id,
            "entity_id": case.entity_id,
            "graph_decision_explanation": None,
            "source": f"decision_api_http_{r.status_code}",
        }
    data = r.json()
    ge = data.get("graph_decision_explanation")
    return {
        "case_id": str(case_id),
        "trace_id": case.trace_id,
        "entity_id": case.entity_id,
        "graph_decision_explanation": ge if isinstance(ge, dict) else None,
        "source": "decision_audit",
        "decision": data.get("decision"),
        "score": data.get("score"),
    }


# ---------- audit trail ----------


@app.get("/v1/cases/{case_id}/audit")
async def case_audit(
    case_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
):
    await _case_for_tenant(session, case_id, tenant_id)
    return {"history": await _trail.get_history(session, "case", str(case_id), limit)}


@app.get("/v1/compliance/evidence")
async def case_control_evidence(tenant_id: str, session: AsyncSession = Depends(get_session), limit: int = 200):
    """Export case/workflow/audit evidence bundle for trust-center audits."""
    q = select(AuditRecord).where(AuditRecord.tenant_id == tenant_id).order_by(AuditRecord.created_at.desc()).limit(max(1, min(limit, 2000)))
    recs = (await session.execute(q)).scalars().all()
    filtered = [
        {
            "id": str(r.id),
            "actor": r.actor,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "changes": r.changes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recs
    ]
    by_action: dict[str, int] = {}
    for r in filtered:
        action = str(r.get("action", "unknown"))
        by_action[action] = by_action.get(action, 0) + 1
    bundle = {
        "tenant_id": tenant_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "controls": [
            {"id": "SOC2-CC8.1", "name": "Case Change Audit Trail", "status": "implemented"},
            {"id": "SOC2-CC7.3", "name": "Workflow-driven Response", "status": "implemented"},
        ],
        "summary": {
            "events_sampled": len(filtered),
            "action_distribution": by_action,
        },
        "evidence": filtered,
    }
    bundle["integrity"] = {
        "algorithm": "sha256+hmac-sha256",
        "key_id": _signing_key_id(),
        "bundle_hash": _bundle_hash(bundle),
        "hash_chain": _hash_chain(filtered),
    }
    bundle["signature"] = _bundle_signature(bundle)
    return bundle


@app.get("/v1/compliance/evidence/keys")
async def case_evidence_keys():
    return {
        "active_key_id": _signing_key_id(),
        "algorithm": "hmac-sha256",
        "rotation_supported": True,
    }


@app.post("/v1/compliance/evidence/verify")
async def verify_case_evidence(body: EvidenceVerifyRequest):
    bundle = dict(body.bundle or {})
    provided_sig = str(bundle.pop("signature", ""))
    integrity = bundle.get("integrity")
    provided_hash = ""
    if isinstance(integrity, dict):
        provided_hash = str(integrity.get("bundle_hash", ""))
        integrity_copy = dict(integrity)
        integrity_copy.pop("bundle_hash", None)
        bundle["integrity"] = integrity_copy
    expected_hash = _bundle_hash(bundle)
    bundle["integrity"] = {
        **(bundle.get("integrity") if isinstance(bundle.get("integrity"), dict) else {}),
        "bundle_hash": expected_hash,
    }
    expected_sig = _bundle_signature(bundle)
    return {
        "valid": bool(provided_sig and hmac.compare_digest(provided_sig, expected_sig) and provided_hash == expected_hash),
        "expected_signature": expected_sig,
        "provided_signature": provided_sig,
        "expected_hash": expected_hash,
        "provided_hash": provided_hash,
        "active_key_id": _signing_key_id(),
    }


# ---------- workflows ----------


@app.get("/v1/workflows")
async def list_workflows():
    return {"workflows": get_workflows()}


@app.post("/v1/workflows/reload")
async def reload_workflows_endpoint():
    load_workflows(os.environ.get("WORKFLOWS_PATH", "./workflows"))
    return {"ok": True, "count": len(get_workflows())}


@app.post("/v1/workflows/trigger")
async def trigger_workflow(request: Request, session: AsyncSession = Depends(get_session)):
    body = await request.json()
    trigger = body.get("trigger", "")
    case_data = body.get("case", {})
    decision_data = body.get("decision", {})
    case_id = case_data.get("id")

    http = request.app.state.http
    ctx = await evaluate_workflows(trigger, case_data, decision=decision_data, http=http)

    if ctx.mutations and case_id:
        result = await session.execute(select(Case).where(Case.id == case_id))
        case = result.scalar_one_or_none()
        if case:
            old_state = CaseOut.model_validate(case).model_dump(mode="json")
            if "priority" in ctx.mutations:
                case.priority = ctx.mutations["priority"]
            if "status" in ctx.mutations:
                case.status = ctx.mutations["status"]
            if "labels" in ctx.mutations:
                existing = list(case.labels) if case.labels else []
                case.labels = sorted(set(existing) | set(ctx.mutations["labels"]))
            if "assigned_team" in ctx.mutations:
                case.assigned_team = ctx.mutations["assigned_team"]
            for comment in ctx.mutations.get("_comments", []):
                session.add(CaseComment(case_id=case.id, author=comment["author"], body=comment["body"]))
            await session.commit()
            await session.refresh(case)

            new_state = CaseOut.model_validate(case).model_dump(mode="json")
            diff = _trail.diff(old_state, new_state)
            if diff:
                await _trail.record(
                    session,
                    actor="workflow-engine",
                    action="workflow_trigger",
                    resource_type="case",
                    resource_id=str(case_id),
                    changes=diff,
                    tenant_id=case.tenant_id,
                )
                await session.commit()

            await _broadcast({"event": "case_updated", "case": new_state})

    return {"actions_executed": ctx.actions_executed, "mutations": {k: v for k, v in ctx.mutations.items() if k != "_comments"}}


@app.get("/v1/cases/{case_id}/sla")
async def case_sla(
    case_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    session: AsyncSession = Depends(get_session),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    from case_api.workflow import compute_sla_deadline

    deadline = compute_sla_deadline(case.priority, case.created_at, sla_hours_override=case.sla_hours_override)
    breached = is_sla_breached(case.priority, case.created_at, sla_hours_override=case.sla_hours_override)
    return {
        "case_id": str(case.id),
        "priority": case.priority,
        "sla_deadline": deadline.isoformat(),
        "breached": breached,
        "status": case.status,
    }


# ---------- SAR generation ----------

_sar_generator = SARGenerator()


@app.post("/v1/cases/{case_id}/sar/generate", status_code=201)
async def generate_sar(
    case_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    _=Depends(require_role("analyst")),
):
    """Generate a SAR/STR from case data.

    Accepts optional JSON body:
      - format: "fincen_xml" | "nca_json" | "generic_json" (default: fincen_xml)
      - transactions: list of transaction dicts (if not supplied, uses empty list)
      - entity_data: subject/entity information
      - filing_institution: override for the filing institution block
    """
    case = await _case_for_tenant(session, case_id, tenant_id)

    body = await request.json() if await request.body() else {}
    sar_format = body.get("format", "fincen_xml")
    transactions = body.get("transactions", [])
    entity_data = body.get("entity_data", {"name": case.entity_id})
    filing_institution = body.get("filing_institution")

    case_dict = CaseOut.model_validate(case).model_dump(mode="json")

    report = await _sar_generator.generate_sar(
        case=case_dict,
        transactions=transactions,
        entity_data=entity_data,
        format=sar_format,
        filing_institution=filing_institution,
    )

    filing = SARFiling(
        case_id=case_id,
        format=sar_format,
        status=report.status,
        narrative=report.narrative,
        report_data=report.json_content
        or {
            "report_id": report.report_id,
            "filing_date": report.filing_date,
            "subject": report.subject,
            "institution": report.institution,
            "transaction_count": len(report.transactions),
        },
        xml_content=report.xml_content,
    )
    session.add(filing)
    await session.commit()
    await session.refresh(filing)

    user = get_current_user(request)
    await _trail.record(
        session,
        actor=user.user_id,
        action="generate_sar",
        resource_type="case",
        resource_id=str(case_id),
        changes={"sar_id": str(filing.id), "format": sar_format},
        tenant_id=case.tenant_id,
    )
    await session.commit()

    return {
        "id": str(filing.id),
        "case_id": str(case_id),
        "report_id": report.report_id,
        "format": sar_format,
        "status": filing.status,
        "narrative": report.narrative,
        "xml_content": report.xml_content,
        "json_content": report.json_content,
        "created_at": filing.created_at.isoformat() if filing.created_at else None,
    }


@app.get("/v1/cases/{case_id}/sar")
async def list_sar_filings(
    case_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    session: AsyncSession = Depends(get_session),
):
    """Retrieve all generated SAR filings for a case."""
    await _case_for_tenant(session, case_id, tenant_id)

    result = await session.execute(select(SARFiling).where(SARFiling.case_id == case_id).order_by(SARFiling.created_at.desc()))
    rows = result.scalars().all()
    return {
        "case_id": str(case_id),
        "filings": [
            {
                "id": str(r.id),
                "format": r.format,
                "status": r.status,
                "narrative": r.narrative,
                "report_data": r.report_data,
                "xml_content": r.xml_content,
                "filed_at": r.filed_at.isoformat() if r.filed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ---------- webhook DLQ management ----------


@app.get("/v1/webhooks/dlq")
async def webhook_dlq(request: Request, _admin=Depends(require_role("admin"))):
    sender: WebhookSender = request.app.state.webhook
    return {"items": sender.get_dlq()}


@app.post("/v1/webhooks/dlq/{webhook_id}/retry")
async def retry_webhook(webhook_id: str, request: Request, _admin=Depends(require_role("admin"))):
    sender: WebhookSender = request.app.state.webhook
    ok = await sender.retry_dlq_item(webhook_id)
    return {"retried": ok}


# ---------- websocket live feed ----------


@app.websocket("/v1/cases/ws")
async def ws_feed(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(ws)


# ---------- static UI ----------

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/ui")
    async def ui_redirect():
        return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
async def root():
    if (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    return {"service": "case-api", "docs": "/docs"}
