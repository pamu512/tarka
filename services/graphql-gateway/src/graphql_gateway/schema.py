from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any

import httpx
import strawberry
from strawberry.scalars import JSON

from graphql_gateway.config import settings

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@strawberry.type
class Case:
    id: strawberry.ID
    tenant_id: str
    title: str
    status: str
    entity_id: str
    trace_id: str
    priority: str
    assigned_team: str | None
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None


@strawberry.type
class GraphNode:
    id: str
    labels: list[str]
    properties: JSON


@strawberry.type
class GraphEdge:
    from_id: str
    to_id: str
    type: str
    properties: JSON


@strawberry.type
class SubGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@strawberry.type
class EvaluateResult:
    trace_id: strawberry.ID
    decision: str
    score: float
    tags: list[str]
    rule_hits: list[str]
    reasons: list[str]
    ml_score: float | None
    recommended_action: str | None = None
    inference_context: JSON | None = None


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@strawberry.input
class DeviceContextInput:
    device_id: str
    platform: str = "web"
    signals: JSON | None = None
    attestation: JSON | None = None


@strawberry.input
class EvaluateInput:
    tenant_id: str
    event_type: str
    entity_id: str
    session_id: str | None = None
    payload: JSON | None = None
    device_context: DeviceContextInput | None = None
    metadata: JSON | None = None


@strawberry.input
class CreateCaseInput:
    tenant_id: str
    title: str
    entity_id: str
    trace_id: str
    priority: str = "medium"
    playbook_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_from_info(info: strawberry.types.Info) -> httpx.AsyncClient:
    return info.context["http_client"]


def _parse_case(data: dict[str, Any]) -> Case:
    return Case(
        id=strawberry.ID(str(data["id"])),
        tenant_id=data["tenant_id"],
        title=data["title"],
        status=data["status"],
        entity_id=data["entity_id"],
        trace_id=data["trace_id"],
        priority=data.get("priority", "medium"),
        assigned_team=data.get("assigned_team"),
        labels=data.get("labels", []),
        created_at=_parse_dt(data.get("created_at")),
        updated_at=_parse_dt(data.get("updated_at")),
    )


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def _raise_for_status(resp: httpx.Response) -> httpx.Response:
    if inspect.isawaitable(resp):
        resp = await resp
    if resp.status_code >= 400:
        body = resp.text
        raise Exception(f"Upstream {resp.request.method} {resp.request.url} returned {resp.status_code}: {body[:500]}")
    return resp


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


@strawberry.type
class Query:
    @strawberry.field
    async def cases(
        self,
        info: strawberry.types.Info,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Case]:
        client = _client_from_info(info)
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        if status is not None:
            params["status"] = status
        url = f"{settings.case_api_url}/v1/cases"
        resp = await client.get(url, params=params)
        resp = await _raise_for_status(resp)
        items = resp.json().get("items", [])
        return [_parse_case(item) for item in items]

    @strawberry.field
    async def case(
        self,
        info: strawberry.types.Info,
        id: strawberry.ID,
        tenant_id: str,
    ) -> Case:
        client = _client_from_info(info)
        url = f"{settings.case_api_url}/v1/cases/{id}"
        resp = await client.get(url, params={"tenant_id": tenant_id})
        resp = await _raise_for_status(resp)
        return _parse_case(resp.json())

    @strawberry.field
    async def subgraph(
        self,
        info: strawberry.types.Info,
        tenant_id: str,
        entity_id: str,
        depth: int = 2,
    ) -> SubGraph:
        client = _client_from_info(info)
        url = f"{settings.graph_service_url}/v1/subgraph"
        resp = await client.get(
            url,
            params={"tenant_id": tenant_id, "entity_id": entity_id, "depth": depth},
        )
        resp = await _raise_for_status(resp)
        data = resp.json()
        nodes = [
            GraphNode(
                id=n["id"],
                labels=n.get("labels", []),
                properties=n.get("properties", {}),
            )
            for n in data.get("nodes", [])
        ]
        edges = [
            GraphEdge(
                from_id=e["from_id"],
                to_id=e["to_id"],
                type=e["type"],
                properties=e.get("properties", {}),
            )
            for e in data.get("edges", [])
        ]
        return SubGraph(nodes=nodes, edges=edges)

    @strawberry.field
    async def entity_tags(
        self,
        info: strawberry.types.Info,
        tenant_id: str,
        entity_id: str,
    ) -> list[str]:
        client = _client_from_info(info)
        url = f"{settings.graph_service_url}/v1/entities/{entity_id}/tags"
        resp = await client.get(url, params={"tenant_id": tenant_id})
        resp = await _raise_for_status(resp)
        return resp.json().get("tags", [])


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def evaluate(
        self,
        info: strawberry.types.Info,
        input: EvaluateInput,
    ) -> EvaluateResult:
        client = _client_from_info(info)
        body: dict[str, Any] = {
            "tenant_id": input.tenant_id,
            "event_type": input.event_type,
            "entity_id": input.entity_id,
        }
        if input.session_id is not None:
            body["session_id"] = input.session_id
        if input.payload is not None:
            body["payload"] = input.payload
        if input.metadata is not None:
            body["metadata"] = input.metadata
        if input.device_context is not None:
            dc: dict[str, Any] = {
                "device_id": input.device_context.device_id,
                "platform": input.device_context.platform,
            }
            if input.device_context.signals is not None:
                dc["signals"] = input.device_context.signals
            if input.device_context.attestation is not None:
                dc["attestation"] = input.device_context.attestation
            body["device_context"] = dc

        url = f"{settings.decision_api_url}/v1/decisions/evaluate"
        resp = await client.post(url, json=body)
        resp = await _raise_for_status(resp)
        data = resp.json()
        return EvaluateResult(
            trace_id=strawberry.ID(str(data["trace_id"])),
            decision=data["decision"],
            score=data["score"],
            tags=data.get("tags", []),
            rule_hits=data.get("rule_hits", []),
            reasons=data.get("reasons", []),
            ml_score=data.get("ml_score"),
            recommended_action=data.get("recommended_action"),
            inference_context=data.get("inference_context"),
        )

    @strawberry.mutation
    async def create_case(
        self,
        info: strawberry.types.Info,
        input: CreateCaseInput,
    ) -> Case:
        client = _client_from_info(info)
        body: dict[str, Any] = {
            "tenant_id": input.tenant_id,
            "title": input.title,
            "entity_id": input.entity_id,
            "trace_id": input.trace_id,
            "priority": input.priority,
        }
        if input.playbook_id:
            body["playbook_id"] = input.playbook_id
        url = f"{settings.case_api_url}/v1/cases"
        resp = await client.post(url, json=body)
        resp = await _raise_for_status(resp)
        return _parse_case(resp.json())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

schema = strawberry.Schema(query=Query, mutation=Mutation)
