"""Tool definitions and execution for the investigation agent."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from investigation_agent.config import settings

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE,
)
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._@:/-]{1,256}$")


def _validate_case_id(case_id: str) -> str:
    """Validate case_id as UUID or safe identifier."""
    case_id = str(case_id).strip()
    if not (_UUID_PATTERN.match(case_id) or _SAFE_ID_PATTERN.match(case_id)):
        raise ValueError(f"Invalid case_id format: {case_id[:50]}")
    return case_id


def _validate_entity_id(entity_id: str) -> str:
    """Validate entity_id contains only safe characters."""
    entity_id = str(entity_id).strip()[:256]
    if not _SAFE_ID_PATTERN.match(entity_id):
        raise ValueError("Invalid entity_id format")
    return entity_id


def _validate_limit(limit: int) -> int:
    """Clamp limit to safe range."""
    return max(1, min(int(limit), 100))


def _validate_depth(depth: int) -> int:
    """Clamp graph depth to safe range."""
    return max(1, min(int(depth), 5))


def _limit_result(result: Any, max_chars: int = 6000) -> dict:
    """Ensure tool results don't overflow the context window."""
    s = json.dumps(result, default=str)
    if len(s) <= max_chars:
        return result
    if isinstance(result, dict):
        trimmed = {}
        for k, v in result.items():
            if isinstance(v, list) and len(v) > 10:
                trimmed[k] = v[:10]
                trimmed[f"{k}_truncated"] = True
                trimmed[f"{k}_total"] = len(v)
            else:
                trimmed[k] = v
        return trimmed
    return result


def _auth_headers() -> dict[str, str]:
    if settings.upstream_api_key:
        return {"x-api-key": settings.upstream_api_key}
    return {}


# ---------- RBAC ----------

def _analyst_allowed(analyst_id: str) -> bool:
    raw = (settings.allowed_analysts or "*").strip()
    if raw == "*":
        return True
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return analyst_id in allowed


# ---------- Tool implementations ----------

async def tool_get_case(http: httpx.AsyncClient, case_id: str, tenant_id: str, analyst_id: str) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        case_id = _validate_case_id(case_id)
    except ValueError as e:
        return {"error": str(e)}
    base = settings.case_api_url.rstrip("/")
    r = await http.get(f"{base}/v1/cases/{case_id}", headers=_auth_headers())
    if r.status_code == 404:
        return {"error": "not_found"}
    r.raise_for_status()
    return _limit_result({"case": r.json()})


async def tool_list_cases(http: httpx.AsyncClient, tenant_id: str, analyst_id: str, limit: int = 20) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    limit = _validate_limit(limit)
    base = settings.case_api_url.rstrip("/")
    r = await http.get(f"{base}/v1/cases", params={"tenant_id": tenant_id, "limit": limit}, headers=_auth_headers())
    r.raise_for_status()
    return _limit_result(r.json())


async def tool_subgraph(http: httpx.AsyncClient, entity_id: str, tenant_id: str, analyst_id: str, depth: int = 2) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        entity_id = _validate_entity_id(entity_id)
    except ValueError as e:
        return {"error": str(e)}
    depth = _validate_depth(depth)
    if not settings.graph_service_url:
        return {"error": "graph_disabled"}
    base = settings.graph_service_url.rstrip("/")
    r = await http.get(f"{base}/v1/subgraph", params={"entity_id": entity_id, "tenant_id": tenant_id, "depth": depth}, headers=_auth_headers())
    r.raise_for_status()
    return _limit_result(r.json())


async def tool_get_entity_tags(http: httpx.AsyncClient, entity_id: str, tenant_id: str, analyst_id: str) -> dict[str, Any]:
    if not _analyst_allowed(analyst_id):
        return {"error": "forbidden"}
    try:
        entity_id = _validate_entity_id(entity_id)
    except ValueError as e:
        return {"error": str(e)}
    if not settings.graph_service_url:
        return {"error": "graph_disabled"}
    base = settings.graph_service_url.rstrip("/")
    r = await http.get(f"{base}/v1/entities/{entity_id}/tags", params={"tenant_id": tenant_id}, headers=_auth_headers())
    r.raise_for_status()
    return _limit_result(r.json())


# ---------- Tool definitions for function calling ----------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_case",
            "description": "Retrieve a specific case by ID",
            "parameters": {
                "type": "object",
                "required": ["case_id"],
                "properties": {
                    "case_id": {"type": "string", "description": "UUID of the case"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_cases",
            "description": "List recent cases in the queue for the current tenant",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20, "description": "Max cases to return"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subgraph",
            "description": "Query the entity graph around a specific entity (accounts, devices, payments, etc.)",
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string", "description": "External ID of the entity to query around"},
                    "depth": {"type": "integer", "default": 2, "description": "Graph traversal depth (1-5)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_tags",
            "description": "Get fraud tags attached to a specific entity in the graph",
            "parameters": {
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string", "description": "External ID of the entity"},
                },
            },
        },
    },
]

TOOL_DISPATCH = {
    "get_case": tool_get_case,
    "list_cases": tool_list_cases,
    "subgraph": tool_subgraph,
    "get_entity_tags": tool_get_entity_tags,
}
