"""
Holy-grail convergence: ingest → outbox (graph + velocity) → analyst transition → label bus.

Uses real rule-engine evaluation (ASGI), embedded TinkerGraph Gremlin mutations, in-memory Redis
``MULTI``/``INCRBY`` semantics, and deterministic retroactive label evaluation (structural tag
helpers — no ``unittest.mock`` response stubs).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

_REPO = Path(__file__).resolve().parents[1]
_SRC_ORCH = _REPO / "services/orchestrator/src"
_SRC_RULE = _REPO / "services/rule_engine/src"
_SRC_INGESTOR = _REPO / "services/ingestor/src"
_SRC_SHARED = _REPO / "packages/shared-core"
_SRC_SHADOW = _REPO / "services/shadow_agent/src"
_SRC_SERVICES = _REPO / "services"
for _p in (_SRC_ORCH, _SRC_RULE, _SRC_INGESTOR, _SRC_SHARED, _SRC_SHADOW, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_E2E_AUTH = "holy-grail-e2e-token"
_INGEST_LATENCY_BUDGET_MS = 3000.0
_GREMLIN_REMOTE_URL = "ws://127.0.0.1:8182/gremlin"
_GREMLIN_DOCKER_IMAGE = "tinkerpop/gremlin-server:3.8.1"
_GREMLIN_DOCKER_NAME = "tarka-e2e-gremlin"


class _VelocityPipeline:
    """Minimal ``redis.asyncio`` pipeline with ``transaction=True`` for velocity ``INCRBY``."""

    def __init__(self, parent: _VelocityRedis) -> None:
        self._parent = parent
        self._ops: list[tuple[str, str, int]] = []

    def incrby(self, key: str, amount: int) -> _VelocityPipeline:
        self._ops.append(("incrby", key, int(amount)))
        return self

    def expire(self, key: str, ttl: int) -> _VelocityPipeline:
        self._ops.append(("expire", key, int(ttl)))
        return self

    async def execute(self) -> list[int]:
        out: list[int] = []
        for op, key, val in self._ops:
            if op == "incrby":
                out.append(await self._parent.incrby(key, val))
            else:
                self._parent.ttls[key] = val
                out.append(1)
        return out


class _VelocityRedis:
    """In-process Redis stand-in implementing ``pipeline(transaction=True)`` + ``INCRBY``."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = False) -> _VelocityPipeline:
        _ = transaction
        return _VelocityPipeline(self)

    async def incrby(self, key: str, amount: int) -> int:
        self.counters[key] = int(self.counters.get(key, 0)) + int(amount)
        return self.counters[key]

    async def aclose(self) -> None:
        return None


def _probe_gremlin_server(url: str) -> bool:
    """Return True when a Gremlin Server accepts a trivial ``inject(1)`` traversal."""
    pytest.importorskip("gremlin_python")
    try:
        from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
        from gremlin_python.process.anonymous_traversal import traversal

        conn = DriverRemoteConnection(url, "g")
        try:
            g = traversal().with_remote(conn)
            return g.inject(1).toList() == [1]
        finally:
            conn.close()
    except Exception:
        return False


def _ensure_gremlin_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Point ``GRAPH_BACKEND=janusgraph`` at a live Gremlin Server.

    Uses ``GREMLIN_REMOTE_URL`` when reachable; otherwise tries to start
    ``tinkerpop/gremlin-server`` via Docker (same contract as deploy compose).
    """
    url = (os.environ.get("GREMLIN_REMOTE_URL") or _GREMLIN_REMOTE_URL).strip()
    if _probe_gremlin_server(url):
        monkeypatch.setenv("GREMLIN_REMOTE_URL", url)
        monkeypatch.setenv("GRAPH_BACKEND", "janusgraph")
        return

    if shutil.which("docker") is None:
        pytest.skip(
            f"Gremlin Server not reachable at {url!r} and docker is unavailable to start one",
        )

    subprocess.run(
        ["docker", "rm", "-f", _GREMLIN_DOCKER_NAME],
        check=False,
        capture_output=True,
    )
    proc = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            _GREMLIN_DOCKER_NAME,
            "-p",
            "8182:8182",
            _GREMLIN_DOCKER_IMAGE,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(
            f"Gremlin Server not reachable at {url!r} and docker run failed: {proc.stderr.strip()}",
        )

    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if _probe_gremlin_server(url):
            monkeypatch.setenv("GREMLIN_REMOTE_URL", url)
            monkeypatch.setenv("GRAPH_BACKEND", "janusgraph")
            return
        time.sleep(1.0)

    pytest.skip(f"Gremlin Server did not become ready at {url!r} within 45s")


def _janusgraph_client_from_env() -> Any:
    from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
    from gremlin_python.process.anonymous_traversal import traversal

    from orchestrator.graph.client import JanusGraphClient

    url = (os.environ.get("GREMLIN_REMOTE_URL") or _GREMLIN_REMOTE_URL).strip()
    conn = DriverRemoteConnection(url, "g")
    g = traversal().with_remote(conn)
    return JanusGraphClient(g, conn, neighbor_max_hops=2)


@dataclass
class _RecordingLabelJetStream:
    """Captures label-bus publishes and validates payload shape."""

    messages: list[dict[str, Any]] = field(default_factory=list)

    async def publish(
        self,
        subject: str,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        from orchestrator.messaging.labels_jetstream import TARKA_LABELS_SUBJECT
        from orchestrator.schemas.label_bus import validate_label_bus_emit_payload

        assert subject == TARKA_LABELS_SUBJECT
        payload = json.loads(body.decode("utf-8"))
        validated = validate_label_bus_emit_payload(payload)
        self.messages.append(
            {
                "subject": subject,
                "payload": validated.model_dump(mode="json"),
                "headers": dict(headers or {}),
            },
        )


class _DirectInferenceGateway:
    async def run_shadow_investigate_inference(self, fn: Any) -> Any:
        return await fn()


def _extract_json_object_after_marker(text: str, marker: str) -> dict[str, Any]:
    start = text.index(marker) + len(marker)
    rest = text[start:].lstrip()
    if not rest.startswith("{"):
        raise ValueError(f"expected JSON object after marker {marker!r}")
    depth = 0
    for idx, ch in enumerate(rest):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(rest[: idx + 1])
                if not isinstance(parsed, dict):
                    raise ValueError("expected JSON object")
                return parsed
    raise ValueError(f"unterminated JSON object after marker {marker!r}")


class _EvidenceDerivedRetroactiveLlm:
    """
    Deterministic retroactive evaluator: derives tags via ``structural_tags_from_evidence_and_disposition``
    and validates them through the same ``parse_retroactive_tags`` gate as production Ollama output.
    """

    async def chat_json_validated(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_self_correction_retries: int = 2,
    ) -> list[str]:
        _ = model, json_self_correction_retries
        from shadow_agent.retroactive_label import parse_retroactive_tags

        from orchestrator.label_propagation import (
            EvidenceManifestSnapshot,
            structural_tags_from_evidence_and_disposition,
        )
        from orchestrator.utils.entity_parser import parse_entities

        system = next(m["content"] for m in messages if m.get("role") == "system")
        manifest_json = _extract_json_object_after_marker(
            system,
            "HISTORIC EVIDENCE MANIFEST (trusted JSON; do not invent fields):\n",
        )
        feedback_json = _extract_json_object_after_marker(
            system,
            "HUMAN FEEDBACK CONTEXT (analyst disposition, chargeback reason, ground truth):\n",
        )

        evidence = EvidenceManifestSnapshot(
            manifest_id=manifest_json.get("manifest_id"),
            trace_steps=tuple(manifest_json.get("trace_steps") or ()),
        )
        disposition = str(feedback_json.get("disposition_text") or "")
        gt = str(feedback_json.get("ground_truth_class") or "FRAUD")
        raw_tags = structural_tags_from_evidence_and_disposition(
            ground_truth_class=gt,
            disposition_text=disposition,
            evidence=evidence,
            parsed=parse_entities(disposition),
            shadow_reasoning=[],
        )
        retro_candidates: list[str] = []
        for tag in raw_tags:
            namespace, _, value = tag.partition(":")
            if not namespace or not value:
                continue
            cleaned_value = (
                value.strip()
                .lower()
                .replace(" ", "_")
                .replace("-", "_")
            )
            retro_candidates.append(f"{namespace.strip().lower()}:{cleaned_value}")

        validated_tags: list[str] = []
        for candidate in retro_candidates:
            try:
                validated_tags.extend(parse_retroactive_tags([candidate]))
            except ValueError:
                continue
        if not validated_tags:
            validated_tags = parse_retroactive_tags(
                [
                    f"ground_truth:{gt.strip().lower()}",
                    f"disposition:{disposition.strip().lower()}",
                ],
            )
        return validated_tags[:12]


_REAL_HTTPX_ASYNC_CLIENT = httpx.AsyncClient


class _RuleEngineAsgiClient:
    """Routes orchestrator upstream HTTP to the real rule-engine FastAPI app."""

    def __init__(self, rule_app: Any, **_kwargs: object) -> None:
        self._transport = httpx.ASGITransport(app=rule_app)

    async def __aenter__(self) -> _RuleEngineAsgiClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        timeout: object | None = None,
    ) -> httpx.Response:
        _ = headers, timeout
        async with _REAL_HTTPX_ASYNC_CLIENT(
            transport=self._transport,
            base_url="http://rule-engine.internal",
        ) as upstream:
            if "/v1/evaluate" in url:
                return await upstream.post("/v1/evaluate", json=json)
            raise AssertionError(f"unexpected upstream url in holy-grail e2e: {url!r}")


def _e2e_flag_ruleset() -> tuple[Any, ...]:
    from rule_engine.ast_schemas import Action, ConditionNode, FieldRef, Operator, Rule

    return (
        Rule(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            name="holy_grail_flag_lane",
            root_node=ConditionNode(
                field=FieldRef(field="amount"),
                operator=Operator.GT,
                value=1.0,
            ),
            action=Action.FLAG,
            priority=1,
        ),
    )


def _rule_engine_asgi_client_factory(rule_app: Any):
    def _factory(*_args: object, **_kwargs: object) -> _RuleEngineAsgiClient:
        return _RuleEngineAsgiClient(rule_app)

    return _factory


@pytest.mark.e2e
def test_holy_grail_convergence_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("aiosqlite")
    pytest.importorskip("gremlin_python")

    import orchestrator.models.cases  # noqa: F401
    import orchestrator.models.decision  # noqa: F401
    import orchestrator.models.label_dlq  # noqa: F401
    import orchestrator.models.normalized_labels  # noqa: F401
    import orchestrator.models.operational_signals  # noqa: F401
    import orchestrator.models.outbox  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401
    import tarka_shared.engine_rules  # noqa: F401
    import tarka_shared.fraud_rules  # noqa: F401

    from datetime import datetime

    from rule_engine.main import create_app as create_rule_app

    from orchestrator.anumana_velocity import (
        build_transaction_velocity_incrby_commands,
        device_hash_token,
        ip_key_token,
    )
    from orchestrator.audit_case_worker import process_new_audit_logs
    from orchestrator.graph.client import (
        LABEL_DEVICE,
        LABEL_IP,
        LABEL_USER,
        REL_ORDERED_FROM_IP,
        REL_USED_DEVICE,
    )
    from orchestrator.main import create_app
    from orchestrator.models.cases import CaseORM, CaseStatus
    from orchestrator.models.decision import DecisionORM
    from orchestrator.models.normalized_labels import NormalizedLabelORM, SOURCE_TYPE_ANALYST_DISPOSITION
    from orchestrator.models.outbox import (
        OUTBOX_EVENT_GRAPH_INGEST,
        OUTBOX_EVENT_LABEL_PROPAGATE,
        OUTBOX_EVENT_VELOCITY_UPDATE,
        OutboxORM,
        OutboxStatus,
    )
    from orchestrator.schemas.domain_boundaries import RiskDecision
    from orchestrator.workers.handlers.base import OutboxProcessorDeps
    from orchestrator.workers.handlers.graph_ingest import _ingest_janus_sync, _parse_transaction
    from orchestrator.workers.outbox_processor import process_outbox_batch
    from shadow_agent.agent import ShadowAgent
    from tarka_shared.audit_trail import AuditLog
    from tarka_shared.database.session import Base

    entity_id = str(uuid.uuid4())
    user_id = f"u-holy-grail-{entity_id[:8]}"
    canvas_fp = "ab" * 32
    device_token = device_hash_token(canvas_fp)
    ingress_ip = "203.0.113.10"
    ip_token = ip_key_token(ingress_ip)
    amount = 42.0
    amount_cents = 4200
    ingest_ts = "2026-05-09T12:00:00+00:00"
    ingest_ts_unix = int(datetime.fromisoformat(ingest_ts).timestamp())

    _ensure_gremlin_server(monkeypatch)
    monkeypatch.setattr("rule_engine.main.load_active_ruleset", lambda: _e2e_flag_ruleset())
    rule_app = create_rule_app()
    rule_app.state.ruleset = _e2e_flag_ruleset()
    monkeypatch.setattr(
        "orchestrator.transaction_ingest.httpx.AsyncClient",
        _rule_engine_asgi_client_factory(rule_app),
    )

    janus_client = _janusgraph_client_from_env()
    monkeypatch.setattr(
        "orchestrator.workers.handlers.graph_ingest._connect_janusgraph",
        lambda: janus_client,
    )

    velocity_redis = _VelocityRedis()
    label_bus = _RecordingLabelJetStream()
    shadow_runtime = SimpleNamespace(
        llm_client=_EvidenceDerivedRetroactiveLlm(),
        gateway=_DirectInferenceGateway(),
        agent=ShadowAgent(llm_client=_EvidenceDerivedRetroactiveLlm()),
    )

    orch_app = create_app(
        rule_engine_url="http://rule-engine.internal",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )

    ingest_body = {
        "entity_id": entity_id,
        "amount": amount,
        "timestamp": ingest_ts,
        "country": "US",
        "metadata": {
            "user_id": user_id,
            "ip": ingress_ip,
            "canvas_fingerprint": canvas_fp,
            "device_fingerprint": device_token,
            "tenant_id": "tenant-holy-grail",
        },
    }

    async def _run() -> None:
        with TestClient(orch_app) as client:
            t0 = time.perf_counter()
            ingest_resp = client.post("/v1/ingest", json=ingest_body)
            ingest_ms = (time.perf_counter() - t0) * 1000.0
            assert ingest_resp.status_code == 200, ingest_resp.text
            assert ingest_ms < _INGEST_LATENCY_BUDGET_MS, f"ingest took {ingest_ms:.1f}ms"

            body = ingest_resp.json()
            assert body["transaction_id"] == entity_id
            risk = RiskDecision.model_validate(body["risk_decision"])
            assert "FLAG" in risk.actions

            fac = orch_app.state.audit_session_factory
            assert fac is not None

            async with fac() as session:
                decision_count = await session.scalar(select(func.count()).select_from(DecisionORM))
                assert int(decision_count or 0) == 1
                decision_row = (
                    await session.execute(select(DecisionORM).where(DecisionORM.entity_id == entity_id))
                ).scalar_one()
                assert decision_row.final_decision == "FLAG"

                audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
                assert int(audit_count or 0) == 1

                outbox_rows = (
                    await session.scalars(
                        select(OutboxORM)
                        .where(OutboxORM.idempotency_key.like(f"%:{entity_id}:%"))
                        .order_by(OutboxORM.event_type.asc()),
                    )
                ).all()
                assert len(outbox_rows) == 2
                by_type = {row.event_type: row for row in outbox_rows}
                assert OUTBOX_EVENT_GRAPH_INGEST in by_type
                assert OUTBOX_EVENT_VELOCITY_UPDATE in by_type
                assert by_type[OUTBOX_EVENT_GRAPH_INGEST].status == OutboxStatus.PENDING.value
                assert by_type[OUTBOX_EVENT_VELOCITY_UPDATE].status == OutboxStatus.PENDING.value
                graph_payload = dict(by_type[OUTBOX_EVENT_GRAPH_INGEST].payload)
                velocity_payload = dict(by_type[OUTBOX_EVENT_VELOCITY_UPDATE].payload)
                assert graph_payload["entity_id"] == entity_id
                assert velocity_payload["amount_cents"] == amount_cents

            deps = OutboxProcessorDeps(
                session_factory=fac,
                graph_client=janus_client,
                redis_client=velocity_redis,
                clickhouse_client=None,
                shadow_runtime=shadow_runtime,
                nats_jetstream=label_bus,
            )
            stats = await process_outbox_batch(deps, batch_size=10)
            assert stats.claimed == 2
            assert stats.completed == 2
            assert stats.failed == 0

            async with fac() as session:
                completed = (
                    await session.scalars(
                        select(OutboxORM).where(OutboxORM.status == OutboxStatus.COMPLETED.value),
                    )
                ).all()
                assert len(completed) == 2

            g = janus_client._g
            user_count = g.V().has(LABEL_USER, "user_id", user_id).count().next()
            device_count = g.V().has(LABEL_DEVICE, "device_id", device_token).count().next()
            ip_count = g.V().has(LABEL_IP, "address", ingress_ip).count().next()
            used_device_edges = (
                g.V()
                .has(LABEL_USER, "user_id", user_id)
                .outE(REL_USED_DEVICE)
                .has("transaction_id", entity_id)
                .count()
                .next()
            )
            ordered_ip_edges = (
                g.V()
                .has(LABEL_USER, "user_id", user_id)
                .outE(REL_ORDERED_FROM_IP)
                .has("transaction_id", entity_id)
                .count()
                .next()
            )
            assert int(user_count) == 1
            assert int(device_count) == 1
            assert int(ip_count) == 1
            assert int(used_device_edges) == 1
            assert int(ordered_ip_edges) == 1

            audit_log_id = int(graph_payload["audit_log_id"])
            transaction = _parse_transaction(graph_payload)
            edge_count_before = (
                g.E().has("transaction_id", entity_id).has("tarka_audit_log_id", audit_log_id).count().next()
            )
            assert int(edge_count_before) >= 1
            _ingest_janus_sync(janus_client, transaction, audit_log_id=audit_log_id)
            edge_count_after = (
                g.E().has("transaction_id", entity_id).has("tarka_audit_log_id", audit_log_id).count().next()
            )
            assert int(edge_count_after) == int(edge_count_before)

            expected_cmds = build_transaction_velocity_incrby_commands(
                tenant_id="tenant-holy-grail",
                device_token=device_token,
                ip_tokens=[ingress_ip],
                amount_cents=amount_cents,
                now_unix=ingest_ts_unix,
            )
            for cmd in expected_cmds:
                observed = velocity_redis.counters.get(cmd.redis_key)
                assert observed == cmd.increment, (
                    f"velocity key {cmd.redis_key!r} expected {cmd.increment}, got {observed!r}"
                )
            assert any(":device:" in key for key in velocity_redis.counters)
            assert any(":ip:" in key and ip_token in key for key in velocity_redis.counters)

            async with fac() as session:
                await process_new_audit_logs(session)
                await session.commit()

            async with fac() as session:
                case_row = (
                    await session.execute(
                        select(CaseORM).where(CaseORM.entity_id == entity_id).limit(1),
                    )
                ).scalar_one()
                assert case_row.status == CaseStatus.OPEN.value
                case_uuid = str(case_row.case_id)

            transition = client.put(
                f"/v1/cases/{case_uuid}/status",
                json={"status": "RESOLVED_FRAUD", "reason_code": "HOLY_GRAIL_FRAUD_CONFIRMED"},
                headers={"X-Auth-Token": _E2E_AUTH},
            )
            assert transition.status_code == 200, transition.text

            async with fac() as session:
                label_row = (
                    await session.scalar(
                        select(NormalizedLabelORM).where(NormalizedLabelORM.entity_id == entity_id),
                    )
                )
                assert label_row is not None
                assert label_row.source_type == SOURCE_TYPE_ANALYST_DISPOSITION
                assert label_row.ground_truth_class == "FRAUD"
                assert label_row.propagated_to_consortium is False

                label_outbox = (
                    await session.scalar(
                        select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_LABEL_PROPAGATE),
                    )
                )
                assert label_outbox is not None
                assert label_outbox.payload["entity_id"] == entity_id
                assert label_outbox.payload["schema"] == "tarka.label_propagate.v1"

            label_stats = await process_outbox_batch(deps, batch_size=10)
            assert label_stats.claimed == 1
            assert label_stats.completed == 1
            assert label_stats.failed == 0
            assert len(label_bus.messages) == 1
            bus_payload = label_bus.messages[0]["payload"]
            assert bus_payload["entity_id"] == entity_id
            assert bus_payload["ground_truth_class"] == "FRAUD"

            async with fac() as session:
                refreshed = await session.get(NormalizedLabelORM, label_row.id)
                assert refreshed is not None
                assert refreshed.propagated_to_consortium is True
                assert any(tag.startswith("ground_truth:") for tag in refreshed.tags)
                published_tags = bus_payload["tags"]
                assert published_tags
                assert any(tag.startswith("ground_truth:") for tag in published_tags)
                assert bus_payload["propagated_to_consortium"] is True
                assert bus_payload.get("schema") == "tarka.normalized_label.v1" or bus_payload.get(
                    "payload_schema",
                ) == "tarka.normalized_label.v1"

    asyncio.run(_run())
