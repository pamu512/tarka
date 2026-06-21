"""Module-level OpenAPI schemas for `@schema.parametrize()` (must bind before pytest collects tests)."""

from __future__ import annotations

from pathlib import Path

from schemathesis import openapi

from tests.contract.bootstrap_app import CONTRACT_API_KEY, ensure_patched_app

_APP = ensure_patched_app()

# Live schema from the running FastAPI app (superset vs checked-in YAML; includes internal routes).
# Auth middleware requires the same service key used for `case.call_and_validate` requests.
SCHEMA_FROM_APP = openapi.from_asgi(
    "/openapi.json", _APP, headers={"X-API-Key": CONTRACT_API_KEY}
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONTRACT_DECISION_API = _REPO_ROOT / "contracts" / "openapi" / "decision-api.yaml"
assert _CONTRACT_DECISION_API.is_file(), f"missing {_CONTRACT_DECISION_API}"

# Frozen git contract — property tests against the published portable description.
SCHEMA_FROM_CONTRACT_YAML = openapi.from_path(_CONTRACT_DECISION_API)
