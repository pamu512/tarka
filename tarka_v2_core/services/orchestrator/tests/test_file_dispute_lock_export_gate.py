"""Gate (Prompt 128): ``POST /v1/cases/{id}/file-dispute`` locks case and returns PDF with graph diagram."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_post_file_dispute_locks_case_and_pdf_includes_graph_viz() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.case_export import EXPORT_CASE_JSON  # noqa: E402
    from orchestrator.dispute_evidence_pdf import PDF_GRAPH_SECTION_TITLE  # noqa: E402
    from orchestrator.graph.client import GraphClient  # noqa: E402
    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from orchestrator.models.decision import DecisionORM  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    class _GraphStub(GraphClient):
        async def ingest_transaction(self, transaction: object) -> None:
            return None

        async def users_connected_to_ip(self, ip: str) -> list[str]:
            return []

        async def get_graph_signals(self, entity_id: str) -> dict[str, object]:
            return {}

        async def device_hardware_risk(
            self,
            device_id: str,
            *,
            current_user_id: str | None = None,
        ) -> dict[str, object]:
            return {}

        async def close(self) -> None:
            return None

        async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, object]:
            uid = anchor_user_id.strip()
            return {
                "found": True,
                "anchor_user_id": uid,
                "network_device_ids": ["gate-dispute-device-128"],
                "network_ip_addresses": ["198.51.100.9"],
                "network_user_ids": [uid],
                "backend": "stub",
            }

    case_uuid = str(uuid.uuid4())
    entity_uuid = str(uuid.uuid4())
    shadow_case_id = entity_uuid
    user_link = "user_file_dispute_gate_128"

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        graph_client_override=_GraphStub(),
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
                    name="dispute-pdf-shadow",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                    graph_snapshot={"nodes": [{"id": "n1"}], "gate": "pdf_zip_128"},
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
                    user_link_key=user_link,
                    entity_id=entity_uuid,
                    status=CaseStatus.OPEN.value,
                    priority=5,
                ),
            )
            s.add(
                DecisionORM(
                    entity_id=entity_uuid,
                    final_decision="FLAG",
                    actions_json=["FLAG"],
                    execution_trace_json=[{"rule_id": "dispute-gate-128", "matched": True}],
                    blocking_rule_id=None,
                    raw_rule_engine_json={"gate": True},
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        r = client.post(
            f"/v1/cases/{case_uuid}/file-dispute",
            headers={"X-Auth-Token": "dispute-gate-token-128"},
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"

        reader = PdfReader(io.BytesIO(r.content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        assert PDF_GRAPH_SECTION_TITLE in text
        assert "gate-dispute-device-128" in text

        z = client.get(
            f"/v1/cases/{case_uuid}/export",
            headers={"X-Auth-Token": "dispute-gate-token-128"},
        )
        assert z.status_code == 200, z.text
        zf = zipfile.ZipFile(io.BytesIO(z.content))
        case_payload = json.loads(zf.read(EXPORT_CASE_JSON).decode())
        assert case_payload["lifecycle_case"]["status"] == CaseStatus.PENDING_ACTION.value
