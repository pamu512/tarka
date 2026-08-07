#!/usr/bin/env python3
"""Wave 6: prove request-signature middleware rejects bad HMAC when secret is set."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


async def _run() -> int:
    sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))
    sys.path.insert(0, str(_REPO / "services" / "shared"))
    import httpx
    from fastapi import FastAPI

    from decision_api.request_signature_middleware import RequestSignatureMiddleware
    from tarka_request_signature import build_signature_headers

    app = FastAPI()

    @app.post("/v1/decisions/evaluate")
    async def _eval() -> dict:
        return {"ok": True}

    app.add_middleware(
        RequestSignatureMiddleware,
        secret="wave6-gate-secret",
        path_prefixes=("/v1/decisions/evaluate",),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = json.dumps({"tenant_id": "t"}).encode()
        bad = await client.post(
            "/v1/decisions/evaluate",
            content=body,
            headers={"content-type": "application/json"},
        )
        if bad.status_code != 401:
            print(
                f"expected 401 without signature, got {bad.status_code}",
                file=sys.stderr,
            )
            return 1
        hdrs = build_signature_headers(body, secret="wave6-gate-secret")
        good = await client.post(
            "/v1/decisions/evaluate",
            content=body,
            headers={"content-type": "application/json", **hdrs},
        )
        if good.status_code != 200:
            print(
                f"expected 200 with valid signature, got {good.status_code}",
                file=sys.stderr,
            )
            return 1
    print("audit_request_signature_gate: OK")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
