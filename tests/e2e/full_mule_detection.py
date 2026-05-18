"""
Prompt 138 — E2E: shared-device mule cluster → Shadow → SAR draft PDF → human approval.

Scenario (synthetic, in-process orchestrator + DuckDB + graph stub):
  1. Five marketplace users transact on the same device fingerprint (DuckDB cluster).
  2. Graph stub returns a dense neighborhood (mule-cluster signal).
  3. Shadow ``/v1/analyze`` is stubbed to return a high-risk executive summary (``MULE_CLUSTER_FLAGGED``).
  4. SAR draft PDF is produced via Saarthi from structured Shadow-shaped JSON.
  5. Human approval is recorded with ``POST /v1/ai/feedback`` (JSONL audit sink).

Run (recommended: orchestrator venv has DuckDB, FastAPI, ReportLab, pypdf)::

    cd tarka_v2_core/services/orchestrator && python -m pytest ../../../tests/e2e/full_mule_detection.py -v
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE = _REPO_ROOT / "tarka_v2_core"
_ORCH_SRC = _CORE / "services" / "orchestrator" / "src"
_INGESTOR_SRC = _CORE / "services" / "ingestor" / "src"
_SHARED_SRC = _CORE / "services" / "shared"
_SAARTHI_SRC = _CORE / "services" / "saarthi" / "src"
for _p in (_ORCH_SRC, _INGESTOR_SRC, _SHARED_SRC, _SAARTHI_SRC):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)


@pytest.fixture()
def _import_domain_modules() -> None:
    """ORM metadata side-effects (same pattern as orchestrator gate tests)."""
    import orchestrator.models.cases  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401
    import tarka_shared.engine_rules  # noqa: F401


SHARED_DEVICE = "mule-device-e2e-138"
USER_IDS = [f"mule_user_{i}_e2e138" for i in range(5)]


class _MuleClusterGraphStub:
    """Graph tier: five distinct users share one device (synthetic neighborhood)."""

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
        users = list(dict.fromkeys([uid] + USER_IDS))
        return {
            "found": True,
            "anchor_user_id": uid,
            "network_user_ids": users,
            "network_transaction_ids": [],
            "network_device_ids": [SHARED_DEVICE],
            "network_ip_addresses": ["198.51.100.138"],
            "blocked_device_touch_count": len(users),
            "neighbor_node_count": 5 + len(users) * 2,
            "edges_summary": [{"kind": "shared_device", "device": SHARED_DEVICE, "accounts": len(users)}],
            "backend": "janusgraph",
        }


async def _stub_shadow_executive_summary(
    *,
    user_id: str,
    graph_context: dict[str, object],
    shadow_base: str,
    shadow_key: str | None,
    timeout_s: float,
) -> dict[str, object]:
    net = graph_context.get("two_hop_network") or {}
    n_accounts = len(net.get("network_user_ids") or [])
    return {
        "source": "shadow",
        "available": True,
        "ai_reasoning": (
            f"MULE_CLUSTER_FLAGGED: {n_accounts} marketplace accounts share device {SHARED_DEVICE}; "
            "velocity and co-location exceed policy; recommend SAR drafting and compliance review."
        ),
        "risk_score": 0.94,
        "is_fraud": True,
        "reasoning": ["shared_device_mule_cluster", "shadow_ai_analyze_complete"],
    }


@pytest.mark.usefixtures("_import_domain_modules")
def test_full_mule_cluster_shadow_sar_pdf_human_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_ENTITY_PROFILE_SKIP_SHADOW", raising=False)

    from ingestor.manifest_schema import TransactionSchema  # noqa: E402
    from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402
    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from saarthi.pdf_generator import REGULATORY_SUMMARY_HEADING, sar_shadow_json_to_formal_pdf_bytes  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    import orchestrator.entity_profile as entity_profile_mod  # noqa: E402

    monkeypatch.setattr(entity_profile_mod, "_shadow_executive_summary", _stub_shadow_executive_summary)

    duck = DuckAnalyticsProvider()
    duck.load()
    base_ts = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    for i, uid in enumerate(USER_IDS):
        duck.append_transaction(
            TransactionSchema(
                entity_id=uuid.uuid4(),
                amount=500.0 + i * 25.0,
                timestamp=datetime(2026, 9, 1, 12, i, 0, tzinfo=UTC),
                metadata={
                    "user_id": uid,
                    "device_id": SHARED_DEVICE,
                    "session_id": "mule-super-session-138",
                },
            ),
        )
    # Noise: same session, different user without device — still inside cluster-loss session union
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=50.0,
            timestamp=datetime(2026, 9, 1, 12, 30, 0, tzinfo=UTC),
            metadata={"user_id": "mule_pass_through_138", "session_id": "mule-super-session-138"},
        ),
    )

    feedback_jsonl = tmp_path / "e2e_human_feedback.jsonl"
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.stub.local",
        audit_database_url="sqlite+aiosqlite:///:memory:",
        graph_client_override=_MuleClusterGraphStub(),
        duck_analytics_provider=duck,
        ai_feedback_jsonl=str(feedback_jsonl),
    )

    entity_id = str(uuid.uuid4())
    anchor = USER_IDS[0]

    async def _seed_postgres() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=entity_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="e2e-mule-cluster",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            log = AuditLog(
                case_id=entity_id,
                action_taken="{}",
                agent_notes=None,
                code_executed=None,
                timestamp=base_ts,
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=str(uuid.uuid4()),
                    transaction_id=int(log.id),
                    user_link_key=anchor,
                    entity_id=entity_id,
                    status=CaseStatus.UNDER_REVIEW.value,
                    priority=90,
                ),
            )
            await s.commit()

    from pypdf import PdfReader  # noqa: E402

    with TestClient(app) as client:
        asyncio.run(_seed_postgres())
        r = client.get(f"/v1/marketplace/users/{anchor}/entity-profile")
        assert r.status_code == 200, r.text
        body = r.json()

        # --- 1–2: five users + one device in graph & Duck cluster ---
        g_users = body["graph_fragment"]["network_user_ids"]
        assert len(g_users) >= 5
        assert SHARED_DEVICE in body["graph_fragment"]["network_device_ids"]
        dm = body["duckdb_metrics"]
        assert dm.get("available") is True
        assert float(dm.get("cluster_loss") or 0) > 100.0
        assert int(dm.get("cluster_loss_txn_count") or 0) >= 5

        # --- 3: Shadow analyzed (stubbed) ---
        se = body["shadow_executive_summary"]
        assert se.get("available") is True
        assert "MULE_CLUSTER_FLAGGED" in (se.get("ai_reasoning") or "")
        assert body["data_sources"].get("shadow_live") is True

        # --- 4: SAR draft PDF from Shadow-shaped payload ---
        laundering = float(dm["cluster_loss"])
        sar_payload = {
            "primary_suspect": f"Coordinated mule ring ({len(USER_IDS)} users / {SHARED_DEVICE})",
            "laundering_volume": laundering,
            "narrative": str(se["ai_reasoning"]),
            "confidence": float(se.get("risk_score") or 0.9),
        }
        pdf_bytes = sar_shadow_json_to_formal_pdf_bytes(sar_payload)
        assert pdf_bytes.startswith(b"%PDF-"), "final SAR PDF must be a valid PDF"

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_text = "".join(page.extract_text() or "" for page in reader.pages)
        assert REGULATORY_SUMMARY_HEADING in pdf_text
        assert "Suspicious Activity Report" in pdf_text or "SAR" in pdf_text
        assert SHARED_DEVICE in pdf_text or str(int(laundering)) in pdf_text.replace(",", "")

        # --- 5: human approval (feedback JSONL) ---
        fb = client.post(
            "/v1/ai/feedback",
            json={
                "rejection_reasons": [
                    "Human approval: SAR draft reviewed; cleared for compliance filing (E2E gate 138).",
                ],
                "tenant_id": DEFAULT_TENANT_ID,
                "trace_id": entity_id,
                "source": "e2e_full_mule_detection",
                "context": "post_sar_pdf_human_signoff",
            },
        )
        assert fb.status_code == 200, fb.text
        assert fb.json().get("ok") is True

    lines = feedback_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row.get("schema") == "tarka.ai_feedback.v1"
    assert "Human approval" in " ".join(row.get("rejection_reasons") or [])
