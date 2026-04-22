from __future__ import annotations
import hashlib
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chitragupta.config import settings
from chitragupta.db import OrchestratorRun, configure_engine, get_session, init_db
from chitragupta.emitters import canonical_input_hash, emit_with_retry, list_emitter_targets
from chitragupta.plugin_sdk import PluginManifest, get_plugin, list_plugins, register_plugin, seed_builtin_plugins

"""HTTP surface: plugin discovery + multi-emitter orchestration runs."""
log = logging.getLogger("chitragupta.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_engine(settings.database_url)
    seed_builtin_plugins()
    await init_db()
    yield


app = FastAPI(title="Tarka Chitragupta", version="0.1.0", lifespan=lifespan)


@app.get("/v1/health")
async def health():
    return {"status": "ok", "server_contract_version": settings.server_contract_version}


@app.get("/v1/plugins")
async def plugins_list():
    return {"plugins": list_plugins(), "server_contract_version": settings.server_contract_version}


@app.post("/v1/plugins/register")
async def plugins_register(manifest: PluginManifest):
    m = register_plugin(manifest)
    return {"ok": True, "plugin": m.model_dump(mode="json")}


@app.get("/v1/plugins/{plugin_id}")
async def plugins_get(plugin_id: str):
    m = get_plugin(plugin_id)
    if not m:
        raise HTTPException(404, "plugin not found")
    return m.model_dump(mode="json")


@app.get("/v1/emitters")
async def emitters_list():
    return {"emitters": list_emitter_targets()}


class RunCreate(BaseModel):
    tenant_id: str
    plugin_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    emitters: list[str] = Field(default_factory=lambda: ["json"])
    simulate_emitter_failures: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Test hook: number of synthetic failures before emitter succeeds.",
    )


@app.post("/v1/runs", status_code=201)
async def runs_create(body: RunCreate, session: AsyncSession = Depends(get_session)):
    p = get_plugin(body.plugin_id)
    if not p:
        raise HTTPException(404, "plugin not found")
    unsupported = [e for e in body.emitters if e not in p.emitter_targets_supported]
    if unsupported:
        raise HTTPException(400, f"emitters not supported by plugin: {unsupported}")
    h = canonical_input_hash(body.input)
    run = OrchestratorRun(
        tenant_id=body.tenant_id,
        plugin_id=body.plugin_id,
        input_hash=h,
        status="pending",
        artifacts={},
        emitter_logs=[],
    )
    session.add(run)
    await session.flush()

    artifacts: dict[str, Any] = {}
    logs: list[dict[str, Any]] = []
    last_error: str | None = None
    try:
        for target in body.emitters:
            data, elog = await emit_with_retry(
                target,
                body.input,
                max_attempts=settings.emitter_max_attempts,
                base_delay=settings.emitter_base_delay_seconds,
                simulate_failures=body.simulate_emitter_failures if target == body.emitters[0] else 0,
            )
            sha = hashlib.sha256(data).hexdigest()
            artifacts[target] = {"sha256": sha, "bytes_len": len(data)}
            logs.append({"emitter": target, "attempts": elog})
        run.status = "completed"
    except Exception:
        log.exception("runs_create failed for plugin_id=%s tenant_id=%s", body.plugin_id, body.tenant_id)
        run.status = "failed"
        last_error = "internal_error"
        run.last_error = last_error
    run.artifacts = artifacts
    run.emitter_logs = logs
    await session.commit()
    await session.refresh(run)

    sanitized_emitter_logs: list[dict[str, Any]] = []
    for entry in run.emitter_logs or []:
        attempts = entry.get("attempts") if isinstance(entry, dict) else None
        sanitized_attempts: list[dict[str, Any]] = []
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, dict):
                    sanitized_attempts.append(
                        {
                            **attempt,
                            "error": None if attempt.get("error") is None else "emitter_failed",
                        }
                    )
        if isinstance(entry, dict):
            sanitized_emitter_logs.append({**entry, "attempts": sanitized_attempts})

    return {
        "run_id": str(run.id),
        "status": run.status,
        "input_hash": run.input_hash,
        "artifacts": run.artifacts,
        "emitter_logs": sanitized_emitter_logs,
        "last_error": "internal_error" if run.last_error else None,
    }


@app.get("/v1/runs/{run_id}")
async def runs_get(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.scalar(select(OrchestratorRun).where(OrchestratorRun.id == run_id))
    if not row:
        raise HTTPException(404, "run not found")
    return {
        "run_id": str(row.id),
        "tenant_id": row.tenant_id,
        "plugin_id": row.plugin_id,
        "status": row.status,
        "input_hash": row.input_hash,
        "artifacts": row.artifacts,
        "emitter_logs": row.emitter_logs,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
