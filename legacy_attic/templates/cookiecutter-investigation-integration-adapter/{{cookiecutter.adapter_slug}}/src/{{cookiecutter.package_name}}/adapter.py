from __future__ import annotations

import os
from typing import Any

import httpx

"""
HTTP adapter mapping Case / Graph / Decision APIs to shapes expected by investigation-agent.

Works out of the box against ``scripts/integration_adapter_mock/server.py`` (default port 18080).

Env (point all three at the mock for local smoke):

- ``CASE_API_URL`` (default ``http://127.0.0.1:18080``)
- ``GRAPH_SERVICE_URL`` (default same as case)
- ``DECISION_API_URL`` (default same as case)
"""

INTEGRATION_PROFILE_ID = "{{ cookiecutter.integration_profile_id }}"


def _base_url(env_var: str, default: str = "http://127.0.0.1:18080") -> str:
    return (os.environ.get(env_var) or default).rstrip("/")


def http_client(timeout_s: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=timeout_s)


def case_base() -> str:
    return _base_url("CASE_API_URL")


def graph_base() -> str:
    return _base_url("GRAPH_SERVICE_URL", case_base())


def decision_base() -> str:
    return _base_url("DECISION_API_URL", case_base())


def list_cases(*, tenant_id: str = "demo") -> dict[str, Any]:
    with http_client() as client:
        r = client.get(f"{case_base()}/v1/cases", params={"tenant_id": tenant_id})
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("list_cases: expected object response")
        return data


def get_case(case_id: str) -> dict[str, Any]:
    with http_client() as client:
        r = client.get(f"{case_base()}/v1/cases/{case_id}")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("get_case: expected object response")
        return data


def get_subgraph(*, entity_id: str = "entity_demo_1") -> dict[str, Any]:
    with http_client() as client:
        r = client.get(
            f"{graph_base()}/v1/subgraph",
            params={"entity_id": entity_id},
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("get_subgraph: expected object response")
        return data


def get_decision_audit(trace_id: str) -> dict[str, Any]:
    with http_client() as client:
        r = client.get(f"{decision_base()}/v1/audit/{trace_id}")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("get_decision_audit: expected object response")
        return data


def example_health_probe() -> dict[str, Any]:
    """Probe Case + Graph + Decision against configured bases (mock-friendly)."""
    errors: list[str] = []
    checks: dict[str, Any] = {}
    try:
        cases = list_cases()
        checks["case"] = {"ok": True, "item_count": len(cases.get("items") or [])}
    except Exception as e:  # noqa: BLE001 — surface connectivity to caller
        errors.append(f"case:{e}")
        checks["case"] = {"ok": False, "error": str(e)[:200]}
    try:
        g = get_subgraph()
        checks["graph"] = {"ok": True, "node_count": len(g.get("nodes") or [])}
    except Exception as e:  # noqa: BLE001
        errors.append(f"graph:{e}")
        checks["graph"] = {"ok": False, "error": str(e)[:200]}
    try:
        audit = get_decision_audit("12345678-1234-5678-9012-123456789abc")
        checks["decision"] = {"ok": True, "decision": audit.get("decision")}
    except Exception as e:  # noqa: BLE001
        errors.append(f"decision:{e}")
        checks["decision"] = {"ok": False, "error": str(e)[:200]}

    status = "ok" if not errors else "degraded"
    return {
        "profile": INTEGRATION_PROFILE_ID,
        "status": status,
        "checks": checks,
        "errors": errors,
    }
