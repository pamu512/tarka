"""Macroservice: decision-api + case-api in one Uvicorn process."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

os.environ["TARKA_CORE_API_SUBAPP"] = "1"

for parent in Path(__file__).resolve().parents:
    candidate = parent / "shared"
    if candidate.is_dir() and (candidate / "observability.py").is_file():
        sys.path.insert(0, str(candidate))
        break
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

import case_api.main as case  # noqa: E402
import decision_api.main as dec  # noqa: E402
from case_api.models import Case  # noqa: E402
from decision_api.json_rules import search_omni_rules  # noqa: E402
from fastapi import Depends, FastAPI, Query  # noqa: E402
from observability import setup_observability  # noqa: E402
from sqlalchemy import String, cast, or_, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from core_api.demo_burst import register_demo_burst_route  # noqa: E402
from core_api.infrastructure.otel import (  # noqa: E402
    init_opentelemetry,
    shutdown_opentelemetry,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with dec.lifespan(dec.app), case.lifespan(case.app):
            yield
    finally:
        shutdown_opentelemetry()


def create_app() -> FastAPI:
    app = FastAPI(title="Tarka Core API", version="1.0.0", lifespan=lifespan)
    init_opentelemetry(app, dec.app, case.app)
    setup_observability(app, "core-api")
    register_demo_burst_route(app)

    @app.get("/v1/health")
    async def health() -> dict:
        return {"status": "ok", "service": "core-api"}

    @app.get("/v1/infra/process-stats")
    async def infra_process_stats() -> dict[str, Any]:
        """Process RSS + worker hint for infra dashboards (core-api interpreter only)."""
        import resource

        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss = float(ru.ru_maxrss)
        if sys.platform == "darwin":
            rss_bytes = int(rss)
        else:
            rss_bytes = int(rss * 1024)
        raw_workers = (
            os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS") or "1"
        ).strip()
        try:
            worker_hint = max(1, int(raw_workers))
        except ValueError:
            worker_hint = 1
        return {
            "rss_bytes": rss_bytes,
            "rss_mb": round(rss_bytes / (1024 * 1024), 2),
            "worker_processes_hint": worker_hint,
            "platform": sys.platform,
        }

    @app.get("/v1/omni-search")
    async def omni_search(
        q: str = Query("", max_length=256),
        tenant_id: str | None = Query(None, max_length=128),
        session: AsyncSession = Depends(case.get_session),
    ) -> dict[str, Any]:
        """Unified palette search: entities + cases (tenant-scoped DB) and active JSON rules (in-process)."""
        needle = (q or "").strip()
        rules = search_omni_rules(needle, 24)
        if not needle:
            return {"entities": [], "cases": [], "rules": []}

        tid = (tenant_id or "").strip()
        if not tid:
            return {"entities": [], "cases": [], "rules": rules}

        esc = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"%{esc}%"
        ent_like = or_(
            Case.entity_id.ilike(pat, escape="\\"),
            Case.title.ilike(pat, escape="\\"),
            Case.trace_id.ilike(pat, escape="\\"),
        )

        entity_rows = (
            await session.execute(
                select(Case.entity_id, Case.tenant_id)
                .where(
                    Case.tenant_id == tid,
                    ent_like,
                )
                .distinct()
                .limit(12)
            )
        ).all()

        entities: list[dict[str, Any]] = []
        seen_ent: set[tuple[str, str]] = set()
        for entity_id, row_tenant in entity_rows:
            eid = str(entity_id)
            rt = str(row_tenant)
            key = (rt, eid)
            if key in seen_ent:
                continue
            seen_ent.add(key)
            entities.append(
                {
                    "entity_id": eid,
                    "tenant_id": rt,
                    "label": eid,
                    "subtitle": f"tenant {rt}",
                }
            )

        case_match = or_(
            Case.title.ilike(pat, escape="\\"),
            Case.entity_id.ilike(pat, escape="\\"),
            Case.trace_id.ilike(pat, escape="\\"),
            cast(Case.id, String).ilike(pat, escape="\\"),
        )
        case_result = await session.execute(
            select(Case)
            .where(
                Case.tenant_id == tid,
                case_match,
            )
            .order_by(Case.updated_at.desc())
            .limit(15)
        )
        cases_out: list[dict[str, Any]] = []
        for row in case_result.scalars().all():
            cases_out.append(
                {
                    "id": str(row.id),
                    "tenant_id": row.tenant_id,
                    "title": row.title,
                    "entity_id": row.entity_id,
                    "trace_id": row.trace_id,
                    "status": row.status,
                    "label": row.title,
                    "subtitle": f"{row.entity_id} · {row.trace_id}",
                }
            )

        return {"entities": entities, "cases": cases_out, "rules": rules}

    app.mount("/decisions", dec.app)
    app.mount("/cases", case.app)
    return app


app = create_app()
