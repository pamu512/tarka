"""Investor / pitch demo: deterministic multi-step burst (transactions → OSINT → block → SAR).

Mounted on core-api at ``POST /v1/internal/demo-burst`` (hidden from OpenAPI).

Public aliases:

- Local Vite dev: ``POST /api/v1/internal/demo-burst`` (see ``frontend/vite.config.ts`` proxy).
- Direct core: ``POST http://localhost:8000/v1/internal/demo-burst``.

Requires:
  - ``TARKA_DEMO_BURST_TOKEN`` — caller must send matching ``X-Tarka-Demo-Burst-Token``.
  - ``X-Api-Key`` — forwarded to decision/case/ingress sub-requests (same as normal API usage).

Optional:
  - ``DEMO_BURST_INGRESS_URL`` — base URL for integration-ingress (default ``http://127.0.0.1:8003``).
    If OSINT fails, the burst still returns HTTP 200 with ``osint`` marked ``fallback`` so pitches do not
    hard-fail when ingress is down.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

DEMO_TENANT_ID = "tarka-investor-demo"
DEMO_ENTITY_ID = "ent-demo-pitch-target"
DEMO_CASE_TITLE = "Investor demo — deterministic SAR queue"
N_TRANSACTIONS = 50


def _require_demo_token(x_tarka_demo_burst_token: str | None) -> None:
    expected = (os.environ.get("TARKA_DEMO_BURST_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "DEMO_BURST_NOT_CONFIGURED",
                "message": "Set TARKA_DEMO_BURST_TOKEN in the core-api environment.",
            },
        )
    got = (x_tarka_demo_burst_token or "").strip()
    if got != expected:
        raise HTTPException(status_code=401, detail={"reason_code": "DEMO_BURST_TOKEN_MISMATCH"})


def _api_key_headers(request: Request) -> dict[str, str]:
    key = (request.headers.get("x-api-key") or request.headers.get("X-Api-Key") or "").strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "DEMO_BURST_API_KEY_REQUIRED",
                "message": "Send X-Api-Key for downstream case/decision/ingress calls.",
            },
        )
    return {"x-api-key": key, "content-type": "application/json", "accept": "application/json"}


def register_demo_burst_route(app: FastAPI) -> None:
    @app.post(
        "/v1/internal/demo-burst",
        include_in_schema=False,
        summary="Internal investor demo burst (hidden)",
        tags=["internal-demo"],
    )
    async def demo_burst(
        request: Request,
        x_tarka_demo_burst_token: str | None = Header(default=None, convert_underscores=False),
    ) -> dict[str, Any]:
        _require_demo_token(x_tarka_demo_burst_token)
        headers = _api_key_headers(request)
        t0 = time.perf_counter()
        out: dict[str, Any] = {
            "tenant_id": DEMO_TENANT_ID,
            "entity_id": DEMO_ENTITY_ID,
            "steps": {},
        }

        try:
            async with asyncio.timeout(42.0):
                inner = await _run_demo_burst_core(local_headers=headers, request_app=request.app)
        except TimeoutError:
            raise HTTPException(
                status_code=504,
                detail={
                    "reason_code": "DEMO_BURST_DEADLINE",
                    "message": "Demo burst exceeded 42s server-side budget.",
                },
            ) from None
        out.update(inner)
        out["ok"] = True
        out["elapsed_ms_total"] = int((time.perf_counter() - t0) * 1000)
        return out


async def _run_demo_burst_core(
    *, local_headers: dict[str, str], request_app: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {"steps": {}}
    headers = local_headers
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request_app, lifespan="off"),
        base_url="http://demo-burst.internal",
        timeout=httpx.Timeout(55.0, connect=5.0),
    ) as local:
        # --- 1) 50 synthetic transactions via decision evaluate ---
        t_tx = time.perf_counter()

        async def one_eval(i: int) -> dict[str, Any]:
            body = {
                "tenant_id": DEMO_TENANT_ID,
                "event_type": "payment",
                "entity_id": DEMO_ENTITY_ID,
                "region": "global",
                "payload": {
                    "amount": 25.0 + float(i),
                    "currency": "USD",
                    "merchant_id": "demo_pitch_merchant",
                    "demo_burst_index": i,
                    "demo_burst_schema": "tarka.investor_pitch/v1",
                },
                "metadata": {"demo_burst": True, "sequence": i},
            }
            idem = {"Idempotency-Key": f"demo-burst-eval-{i:03d}"}
            r = await local.post(
                "/decisions/v1/decisions/evaluate", json=body, headers={**headers, **idem}
            )
            if r.status_code >= 400:
                return {"index": i, "ok": False, "status": r.status_code, "body": r.text[:500]}
            return {"index": i, "ok": True, "status": r.status_code}

        # Keep concurrency modest so SQLite micro profiles avoid ``database is locked`` under burst load.
        sem = asyncio.Semaphore(8)

        async def guarded(i: int) -> dict[str, Any]:
            async with sem:
                return await one_eval(i)

        results = await asyncio.gather(*[guarded(i) for i in range(N_TRANSACTIONS)])
        failures = [x for x in results if not x.get("ok")]
        if failures:
            raise HTTPException(
                status_code=502,
                detail={
                    "reason_code": "DEMO_BURST_EVALUATE_FAILED",
                    "failures": failures[:5],
                    "failure_count": len(failures),
                },
            )
        out["steps"]["synthetic_transactions"] = {
            "count": N_TRANSACTIONS,
            "elapsed_ms": int((time.perf_counter() - t_tx) * 1000),
        }

        # --- 2) OSINT payload (integration-ingress; fallback if unreachable) ---
        t_os = time.perf_counter()
        ingress_base = (os.environ.get("DEMO_BURST_INGRESS_URL") or "http://127.0.0.1:8003").rstrip(
            "/"
        )
        osint_payload: dict[str, Any] = {
            "ip": "8.8.8.8",
            "tenant_id": DEMO_TENANT_ID,
            "data_residency_region": "US",
        }
        osint_block: dict[str, Any] = {"mode": "live", "ingress_base": ingress_base}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(14.0, connect=2.0)) as ext:
                r_os = await ext.post(
                    f"{ingress_base}/v1/osint", json=osint_payload, headers=headers
                )
            osint_block["http_status"] = r_os.status_code
            if r_os.status_code >= 400:
                osint_block["mode"] = "fallback"
                osint_block["body_preview"] = r_os.text[:400]
                osint_block["canned"] = {
                    "risk_level": "unknown",
                    "note": "Ingress returned non-success; canned summary for demo continuity.",
                }
            else:
                try:
                    osint_block["payload"] = r_os.json()
                except Exception:
                    osint_block["payload"] = {"raw": r_os.text[:2000]}
        except Exception as exc:
            osint_block["mode"] = "fallback"
            osint_block["error"] = str(exc)
            osint_block["canned"] = {
                "risk_score": 21,
                "risk_level": "low",
                "note": "Ingress unreachable — deterministic placeholder for investor pitch.",
            }
        osint_block["elapsed_ms"] = int((time.perf_counter() - t_os) * 1000)
        out["steps"]["osint"] = osint_block

        # --- 3) Force block (blacklist) on the demo entity ---
        t_bl = time.perf_counter()
        bl_body = {
            "tenant_id": DEMO_TENANT_ID,
            "entity_id": DEMO_ENTITY_ID,
            "reason": "demo_burst_investor_pitch_block",
            "created_by": "demo-burst",
            "metadata": {"demo_burst": True},
        }
        r_bl = await local.post("/decisions/v1/lists/blacklist", json=bl_body, headers=headers)
        if r_bl.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail={
                    "reason_code": "DEMO_BURST_BLOCKLIST_FAILED",
                    "status": r_bl.status_code,
                    "body": r_bl.text[:800],
                },
            )
        try:
            bl_json = r_bl.json()
        except Exception:
            bl_json = {"raw": r_bl.text[:500]}
        out["steps"]["entity_block"] = {
            "http_status": r_bl.status_code,
            "response": bl_json,
            "elapsed_ms": int((time.perf_counter() - t_bl) * 1000),
        }

        # --- 4) Case + SAR queue (generate creates filing + intent; may queue transport) ---
        t_case = time.perf_counter()
        trace = str(uuid.uuid5(uuid.NAMESPACE_URL, "tarka.investor-demo-burst-case"))
        case_body = {
            "tenant_id": DEMO_TENANT_ID,
            "title": DEMO_CASE_TITLE,
            "entity_id": DEMO_ENTITY_ID,
            "trace_id": trace,
            "priority": "high",
        }
        r_case = await local.post("/cases/v1/cases", json=case_body, headers=headers)
        if r_case.status_code != 201:
            raise HTTPException(
                status_code=502,
                detail={
                    "reason_code": "DEMO_BURST_CREATE_CASE_FAILED",
                    "status": r_case.status_code,
                    "body": r_case.text[:800],
                },
            )
        case_json = r_case.json()
        case_id = case_json.get("id")
        if not case_id:
            raise HTTPException(
                status_code=502,
                detail={"reason_code": "DEMO_BURST_CASE_ID_MISSING", "case": case_json},
            )
        out["steps"]["case"] = {
            "id": str(case_id),
            "elapsed_ms": int((time.perf_counter() - t_case) * 1000),
        }

        t_sar = time.perf_counter()
        txs = [
            {
                "trace_id": f"demo-pitch-{i:03d}",
                "amount": 25.0 + float(i),
                "currency": "USD",
                "ts": "2026-01-15T12:00:00Z",
                "direction": "DEBIT",
            }
            for i in range(N_TRANSACTIONS)
        ]
        sar_body = {
            "format": "generic_json",
            "transactions": txs,
            "entity_data": {"name": DEMO_ENTITY_ID, "role": "subject", "demo_burst": True},
            "filing_institution": {
                "filer_tin": "000000000",
                "financial_institution_name": "Tarka Demo Financial (pitch)",
            },
        }
        q = quote(DEMO_TENANT_ID, safe="")
        r_sar = await local.post(
            f"/cases/v1/cases/{case_id}/sar/generate?tenant_id={q}",
            json=sar_body,
            headers=headers,
        )
        if r_sar.status_code != 201:
            raise HTTPException(
                status_code=502,
                detail={
                    "reason_code": "DEMO_BURST_SAR_FAILED",
                    "status": r_sar.status_code,
                    "body": r_sar.text[:1200],
                },
            )
        try:
            sar_json = r_sar.json()
        except Exception:
            sar_json = {"raw": r_sar.text[:1200]}
        out["steps"]["sar"] = {
            "http_status": r_sar.status_code,
            "response": sar_json,
            "elapsed_ms": int((time.perf_counter() - t_sar) * 1000),
        }

    return out
