#!/usr/bin/env python3
"""Tenant binding smoke checks for CI and staged rollout validation (Q1-E02)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SHARED = _REPO / "services" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _run_matrix(*, binding_required: bool) -> list[str]:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from auth import require_api_key
    from tenant_binding import tenant_binding_required as tenant_binding_flag

    errors: list[str] = []
    os.environ["TENANT_BINDING_REQUIRED"] = "true" if binding_required else "false"
    os.environ["API_KEYS"] = "smoke-key"
    os.environ["API_KEY_TENANT_MAP"] = json.dumps({"smoke-key": "tenant_alpha"})
    os.environ.pop("ALLOW_INSECURE_NO_AUTH", None)

    if tenant_binding_flag() != binding_required:
        errors.append(
            f"tenant_binding_required()={tenant_binding_flag()} expected {binding_required}",
        )

    app = FastAPI(dependencies=[Depends(require_api_key)])

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    with TestClient(app) as client:
        same = client.get("/probe?tenant_id=tenant_alpha", headers={"x-api-key": "smoke-key"})
        cross = client.get("/probe?tenant_id=tenant_beta", headers={"x-api-key": "smoke-key"})
        missing = client.get("/probe", headers={"x-api-key": "smoke-key"})
        health = client.get("/v1/health")

    if same.status_code != 200:
        errors.append(f"same-tenant probe expected 200 got {same.status_code}: {same.text}")
    if binding_required and cross.status_code != 403:
        errors.append(f"cross-tenant probe expected 403 got {cross.status_code}: {cross.text}")
    if not binding_required and cross.status_code != 200:
        errors.append(
            f"cross-tenant probe with binding off expected 200 got {cross.status_code}: {cross.text}",
        )
    if binding_required and missing.status_code != 400:
        errors.append(f"missing-tenant probe expected 400 got {missing.status_code}: {missing.text}")
    if not binding_required and missing.status_code != 200:
        errors.append(
            f"missing-tenant probe with binding off expected 200 got {missing.status_code}: {missing.text}",
        )
    if health.status_code != 404:
        # require_api_key only skips known health paths when mounted; unmounted path is fine.
        pass

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-binding-required",
        choices=("true", "false"),
        default=os.environ.get("TENANT_BINDING_REQUIRED", "false").lower(),
        help="Exercise TENANT_BINDING_REQUIRED=true|false matrix slice",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Run smoke for true and false (ignores --tenant-binding-required)",
    )
    args = parser.parse_args()

    slices = ("true", "false") if args.both else (args.tenant_binding_required,)
    all_errors: list[str] = []
    for raw in slices:
        required = _truthy(raw)
        errs = _run_matrix(binding_required=required)
        for err in errs:
            all_errors.append(f"TENANT_BINDING_REQUIRED={raw}: {err}")

    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        return 1

    print(f"OK: tenant binding smoke passed for {', '.join(slices)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
