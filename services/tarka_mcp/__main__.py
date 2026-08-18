"""Thin MCP stdio server for Tarka decision context graph tools.

ponytail: minimal JSON-RPC over stdin/stdout — enough for IDE/agent wiring.
Ceiling: no OAuth, no resource subscriptions; upgrade path is full MCP SDK.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

TOOLS = [
    {
        "name": "record_decision",
        "description": "Record a decision in the Tarka decision context graph",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["evaluate", "agent_advise", "human_disposition", "policy_gate"],
                },
                "category": {"type": "string"},
                "scenario": {"type": "string"},
                "outcome": {"type": "string"},
                "reasoning": {"type": "string"},
                "entity_external_ids": {"type": "array", "items": {"type": "string"}},
                "prior_decision_id": {"type": "string"},
                "relationship": {
                    "type": "string",
                    "enum": ["CAUSED", "INFLUENCED", "PRECEDENT_FOR", "SUPERSEDES"],
                },
            },
            "required": ["tenant_id", "kind", "category", "scenario", "outcome"],
        },
    },
    {
        "name": "get_decision_chain",
        "description": "Trace causal parents of a decision",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "external_id": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            "required": ["tenant_id", "external_id"],
        },
    },
    {
        "name": "get_decision_impact",
        "description": "Blast-radius: downstream decisions influenced by this one",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "external_id": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            "required": ["tenant_id", "external_id"],
        },
    },
    {
        "name": "find_precedent_decisions",
        "description": "Rank similar past decisions by entity/category/outcome/rule overlap",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "from_external_id": {"type": "string"},
                "category": {"type": "string"},
                "outcome": {"type": "string"},
                "kind": {"type": "string"},
                "entity_external_id": {"type": "string"},
                "rule_ids": {"type": "string", "description": "Comma-separated rule ids"},
                "limit": {"type": "integer"},
            },
            "required": ["tenant_id"],
        },
    },
]


def _base() -> str:
    for key in ("DECISION_GRAPH_URL", "GRAPH_SERVICE_URL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v.rstrip("/")
    return "http://127.0.0.1:8082"


def _headers() -> dict[str, str]:
    key = (os.environ.get("GRAPH_SERVICE_API_KEY") or os.environ.get("API_KEY") or "").strip()
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def _http_json(
    method: str, path: str, *, params: dict | None = None, body: dict | None = None
) -> Any:
    import urllib.error
    import urllib.parse
    import urllib.request

    url = _base() + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:500]}
    except Exception as e:
        return {"error": str(e)}


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "record_decision":
        payload = {
            "tenant_id": arguments["tenant_id"],
            "kind": arguments["kind"],
            "category": arguments["category"],
            "scenario": arguments["scenario"],
            "outcome": arguments["outcome"],
            "reasoning": arguments.get("reasoning") or "",
            "entity_external_ids": arguments.get("entity_external_ids") or [],
        }
        prior = (arguments.get("prior_decision_id") or "").strip()
        if prior:
            payload["edges"] = [
                {
                    "from_external_id": prior,
                    "relationship": arguments.get("relationship") or "INFLUENCED",
                }
            ]
        return _http_json("POST", "/v1/decisions", body=payload)
    if name == "get_decision_chain":
        return _http_json(
            "GET",
            f"/v1/decisions/{arguments['external_id']}/chain",
            params={
                "tenant_id": arguments["tenant_id"],
                "max_depth": arguments.get("max_depth") or 5,
            },
        )
    if name == "get_decision_impact":
        return _http_json(
            "GET",
            f"/v1/decisions/{arguments['external_id']}/impact",
            params={
                "tenant_id": arguments["tenant_id"],
                "max_depth": arguments.get("max_depth") or 5,
            },
        )
    if name == "find_precedent_decisions":
        return _http_json(
            "GET",
            "/v1/decisions/precedents",
            params={
                "tenant_id": arguments["tenant_id"],
                "from_external_id": arguments.get("from_external_id"),
                "category": arguments.get("category"),
                "outcome": arguments.get("outcome"),
                "kind": arguments.get("kind"),
                "entity_external_id": arguments.get("entity_external_id"),
                "rule_ids": arguments.get("rule_ids"),
                "limit": arguments.get("limit") or 10,
            },
        )
    return {"error": f"unknown tool {name}"}


def _reply(msg_id: Any, result: Any) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def _reply_error(msg_id: Any, code: int, message: str) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})
        + "\n"
    )
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            _reply(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tarka-mcp", "version": "0.1.0"},
                },
            )
        elif method == "tools/list":
            _reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                out = call_tool(str(name), args if isinstance(args, dict) else {})
                _reply(
                    msg_id,
                    {"content": [{"type": "text", "text": json.dumps(out, default=str)}]},
                )
            except Exception as e:
                _reply_error(msg_id, -32000, str(e))
        elif method == "notifications/initialized":
            continue
        elif msg_id is not None:
            _reply_error(msg_id, -32601, f"method not found: {method}")


if __name__ == "__main__":
    main()
