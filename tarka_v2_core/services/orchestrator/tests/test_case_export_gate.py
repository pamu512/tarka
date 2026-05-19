"""Gate (Prompt 116): ``GET /v1/cases/{id}/export`` ZIP contains case, graph snapshot, and Rust trace JSON."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_get_case_export_zip_contains_case_graph_and_rust_trace() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.case_export import (  # noqa: E402
        EXPORT_CASE_JSON,
        EXPORT_GRAPH_SNAPSHOT_JSON,
        EXPORT_MANIFEST_JSON,
        EXPORT_RUST_TRACE_JSON,
        EXPORT_SIGNATURE_TXT,
    )
    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from orchestrator.models.decision import DecisionORM  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    hmac_key = b"gate-compliance-hmac-116"
    case_uuid = str(uuid.uuid4())
    entity_uuid = str(uuid.uuid4())
    shadow_case_id = entity_uuid

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        compliance_export_hmac_key=hmac_key,
        audit_background_poll=False,
    )

    async def _seed() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=shadow_case_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="export-shadow-case",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                    graph_snapshot={"gate": "graph_snapshot_116", "nodes": [{"id": "u1"}]},
                ),
            )
            log = AuditLog(
                case_id=shadow_case_id,
                action_taken="{}",
                agent_notes=None,
                code_executed=None,
                timestamp=datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC),
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=case_uuid,
                    transaction_id=int(log.id),
                    user_link_key="user_export_116",
                    entity_id=entity_uuid,
                    status=CaseStatus.OPEN.value,
                    priority=2,
                ),
            )
            s.add(
                DecisionORM(
                    entity_id=entity_uuid,
                    final_decision="FLAG",
                    actions_json=["FLAG"],
                    execution_trace_json=[{"rule_id": "gate-rust-trace", "matched": True}],
                    blocking_rule_id=None,
                    raw_rule_engine_json={"gate": True, "trace_ref": "rust_evaluator"},
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        r = client.get(
            f"/v1/cases/{case_uuid}/export",
            headers={"X-Auth-Token": "export-token-116"},
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/zip")

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        assert EXPORT_CASE_JSON in names
        assert EXPORT_GRAPH_SNAPSHOT_JSON in names
        assert EXPORT_RUST_TRACE_JSON in names
        assert EXPORT_MANIFEST_JSON in names
        assert EXPORT_SIGNATURE_TXT in names

        case_payload = json.loads(zf.read(EXPORT_CASE_JSON).decode())
        assert case_payload["lifecycle_case"]["case_id"] == case_uuid
        assert case_payload["shadow_case"]["id"] == shadow_case_id

        graph_payload = json.loads(zf.read(EXPORT_GRAPH_SNAPSHOT_JSON).decode())
        assert graph_payload.get("gate") == "graph_snapshot_116"

        rust_payload = json.loads(zf.read(EXPORT_RUST_TRACE_JSON).decode())
        assert rust_payload.get("execution_trace") == [
            {"rule_id": "gate-rust-trace", "matched": True}
        ]

        manifest_bytes = zf.read(EXPORT_MANIFEST_JSON)
        manifest = json.loads(manifest_bytes.decode())
        assert "files" in manifest
        for fn in (EXPORT_CASE_JSON, EXPORT_GRAPH_SNAPSHOT_JSON, EXPORT_RUST_TRACE_JSON):
            assert fn in manifest["files"]
            expected = hashlib.sha256(zf.read(fn)).hexdigest()
            assert manifest["files"][fn] == expected

        sig = zf.read(EXPORT_SIGNATURE_TXT).decode().strip()
        expected_sig = hmac.new(hmac_key, manifest_bytes, hashlib.sha256).hexdigest()
        assert sig == expected_sig
