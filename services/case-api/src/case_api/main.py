import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.config import settings
from case_api.db import Base, get_session, init_db
from case_api.models import Case, CaseComment, SARFiling
from case_api.sar import SARGenerator
from case_api.dispute_api import router as dispute_router
from case_api.schemas import CaseOut, CommentIn, CreateCaseRequest, LabelsIn
from case_api.retention import DEFAULT_RETENTION_DAYS, retention_loop
from case_api.workflow import evaluate_workflows, get_workflows, is_sla_breached, load_workflows

_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from observability import setup_observability  # noqa: E402
from auth_rbac import setup_auth, require_role, get_current_user  # noqa: E402
from rate_limiter import setup_rate_limiter  # noqa: E402
from audit_trail import AuditTrail, create_audit_model  # noqa: E402
from webhook_sender import WebhookSender  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

AuditRecord = create_audit_model(Base)
_trail = AuditTrail(AuditRecord)

# ---------- websocket connections for live feed ----------
_ws_clients: set[WebSocket] = set()


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
_cors_origins = [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
] if settings.cors_origins else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(dispute_router)


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/cases", response_model=dict)
async def list_cases(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
    limit: int = 50,
):
    q = select(Case).where(Case.tenant_id == tenant_id)
    if status:
        q = q.where(Case.status == status)
    q = q.order_by(Case.updated_at.desc()).limit(limit)
    result = await session.execute(q)
    rows = result.scalars().all()
    return {"items": [CaseOut.model_validate(r).model_dump() for r in rows]}


@app.post("/v1/cases", response_model=CaseOut, status_code=201)
async def create_case(body: CreateCaseRequest, request: Request, session: AsyncSession = Depends(get_session)):
    user = get_current_user(request)
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
        session, actor=user.user_id, action="create_case",
        resource_type="case", resource_id=str(c.id),
        changes={"status": {"old": None, "new": "open"}, "priority": {"old": None, "new": body.priority}},
        tenant_id=body.tenant_id,
    )
    await session.commit()

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
                session, actor="workflow-engine", action="workflow_mutation",
                resource_type="case", resource_id=str(c.id),
                changes=diff, tenant_id=body.tenant_id,
            )
            await session.commit()

    await _broadcast({"event": "case_created", "case": CaseOut.model_validate(c).model_dump(mode="json")})
    return CaseOut.model_validate(c)


@app.get("/v1/cases/{case_id}", response_model=CaseOut)
async def get_case(case_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Case).where(Case.id == case_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "not found")
    return CaseOut.model_validate(row)


@app.patch("/v1/cases/{case_id}")
async def update_case(
    case_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = get_current_user(request)
    result = await session.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "not found")

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
            session, actor=user.user_id, action="update_case",
            resource_type="case", resource_id=str(case_id),
            changes=diff, tenant_id=case.tenant_id,
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
):
    result = await session.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "not found")
    session.add(CaseComment(case_id=case_id, author=body.author, body=body.body))
    await session.commit()

    user = get_current_user(request)
    await _trail.record(
        session, actor=user.user_id, action="add_comment",
        resource_type="case", resource_id=str(case_id),
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
):
    result = await session.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "not found")
    old_labels = list(case.labels) if case.labels else []
    case.labels = sorted(set(old_labels) | set(body.labels))
    await session.commit()

    user = get_current_user(request)
    await _trail.record(
        session, actor=user.user_id, action="update_labels",
        resource_type="case", resource_id=str(case_id),
        changes={"labels": {"old": old_labels, "new": case.labels}},
        tenant_id=case.tenant_id,
    )
    await session.commit()
    return {"ok": True, "labels": case.labels}


@app.get("/v1/cases/{case_id}/graph")
async def case_graph(case_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session), depth: int = 2):
    if not settings.graph_service_url:
        return {"nodes": [], "edges": [], "message": "GRAPH_SERVICE_URL not set"}
    result = await session.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "not found")
    base = settings.graph_service_url.rstrip("/")
    http: httpx.AsyncClient = request.app.state.http
    r = await http.get(f"{base}/v1/subgraph", params={"entity_id": case.entity_id, "tenant_id": case.tenant_id, "depth": depth})
    r.raise_for_status()
    return r.json()


# ---------- audit trail ----------

@app.get("/v1/cases/{case_id}/audit")
async def case_audit(case_id: uuid.UUID, session: AsyncSession = Depends(get_session), limit: int = 50):
    return {"history": await _trail.get_history(session, "case", str(case_id), limit)}


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
                    session, actor="workflow-engine", action="workflow_trigger",
                    resource_type="case", resource_id=str(case_id),
                    changes=diff, tenant_id=case.tenant_id,
                )
                await session.commit()

            await _broadcast({"event": "case_updated", "case": new_state})

    return {"actions_executed": ctx.actions_executed, "mutations": {k: v for k, v in ctx.mutations.items() if k != "_comments"}}


@app.get("/v1/cases/{case_id}/sla")
async def case_sla(case_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "not found")
    from case_api.workflow import compute_sla_deadline
    deadline = compute_sla_deadline(case.priority, case.created_at)
    breached = is_sla_breached(case.priority, case.created_at)
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
):
    """Generate a SAR/STR from case data.

    Accepts optional JSON body:
      - format: "fincen_xml" | "nca_json" | "generic_json" (default: fincen_xml)
      - transactions: list of transaction dicts (if not supplied, uses empty list)
      - entity_data: subject/entity information
      - filing_institution: override for the filing institution block
    """
    result = await session.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "case not found")

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
        report_data=report.json_content or {
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
        session, actor=user.user_id, action="generate_sar",
        resource_type="case", resource_id=str(case_id),
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
    session: AsyncSession = Depends(get_session),
):
    """Retrieve all generated SAR filings for a case."""
    case_result = await session.execute(select(Case).where(Case.id == case_id))
    if not case_result.scalar_one_or_none():
        raise HTTPException(404, "case not found")

    result = await session.execute(
        select(SARFiling)
        .where(SARFiling.case_id == case_id)
        .order_by(SARFiling.created_at.desc())
    )
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
async def webhook_dlq(request: Request):
    sender: WebhookSender = request.app.state.webhook
    return {"items": sender.get_dlq()}


@app.post("/v1/webhooks/dlq/{webhook_id}/retry")
async def retry_webhook(webhook_id: str, request: Request):
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
