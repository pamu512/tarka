"""SAR transport ops board (DB) and force SFTP sync rate limit + SFTP error mapping."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from case_api.db import SessionLocal
from case_api.models import Case, SARFiling, SarFiling
from case_api.sar_transport import SAR_APPROVED, SAR_SFTP_QUEUED, SAR_TRANSMITTED
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


@pytest.fixture(autouse=True)
def _reset_force_sftp_sync_clock() -> None:
    import case_api.sar_transport_monitor_api as mon

    mon._last_force_sync_monotonic = 0.0
    yield
    mon._last_force_sync_monotonic = 0.0


def test_sar_transport_board_reflects_database_columns() -> None:
    """Board columns are driven from ``sar_filing_intents`` status values."""
    import asyncio

    tid = "tenant-sar-board-1"
    case_a = uuid.uuid4()
    case_b = uuid.uuid4()
    case_c = uuid.uuid4()
    art_a = uuid.uuid4()
    art_b = uuid.uuid4()
    art_c = uuid.uuid4()
    int_a = uuid.uuid4()
    int_b = uuid.uuid4()
    int_c = uuid.uuid4()

    async def seed() -> None:
        async with SessionLocal() as session, session.begin():
            for cid in (case_a, case_b, case_c):
                session.add(
                    Case(
                        id=cid,
                        tenant_id=tid,
                        title="sar-board",
                        status="open",
                        entity_id="e1",
                        trace_id=f"tr-{cid.hex[:8]}",
                    )
                )
            for aid, cid in ((art_a, case_a), (art_b, case_b), (art_c, case_c)):
                session.add(
                    SARFiling(
                        id=aid,
                        case_id=cid,
                        format="fincen_xml",
                        status="draft",
                        narrative="n",
                        report_data={"report_id": "R1"},
                        xml_content="<EFilingBatchXML/>",
                    )
                )
            session.add(
                SarFiling(
                    id=int_a,
                    tenant_id=tid,
                    case_id=case_a,
                    sar_artifact_id=art_a,
                    status=SAR_APPROVED,
                    filing_data={},
                    audit_trail={},
                )
            )
            session.add(
                SarFiling(
                    id=int_b,
                    tenant_id=tid,
                    case_id=case_b,
                    sar_artifact_id=art_b,
                    status=SAR_SFTP_QUEUED,
                    filing_data={},
                    audit_trail={},
                )
            )
            session.add(
                SarFiling(
                    id=int_c,
                    tenant_id=tid,
                    case_id=case_c,
                    sar_artifact_id=art_c,
                    status=SAR_TRANSMITTED,
                    filing_data={},
                    audit_trail={},
                )
            )

    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        with TestClient(app) as client:
            asyncio.run(seed())
            r = client.get(
                "/v1/cases/ops/sar-transport/board",
                params={"tenant_id": tid},
                headers=_api_headers(),
            )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_id"] == tid
    assert data["columns"]["pending"]["count"] == 1
    assert data["columns"]["claimed"]["count"] == 1
    assert data["columns"]["uploaded"]["count"] == 1
    assert {
        data["columns"]["pending"]["items"][0]["id"],
        data["columns"]["claimed"]["items"][0]["id"],
        data["columns"]["uploaded"]["items"][0]["id"],
    } == {str(int_a), str(int_b), str(int_c)}


def test_force_sftp_sync_rate_limited_within_60s() -> None:
    with (
        patch("case_api.main.evaluate_workflows", new_callable=AsyncMock),
        patch(
            "case_api.sar_transport_monitor_api.process_sar_transport_once", new_callable=AsyncMock
        ) as proc,
    ):
        from case_api.main import app

        proc.return_value = False
        with TestClient(app) as client:
            r1 = client.post("/v1/cases/ops/sar-transport/force-sftp-sync", headers=_api_headers())
            assert r1.status_code == 200, r1.text
            r2 = client.post("/v1/cases/ops/sar-transport/force-sftp-sync", headers=_api_headers())
            assert r2.status_code == 429
            assert int(r2.headers.get("Retry-After", "0")) >= 1


def test_force_sftp_sync_maps_socket_timeout_to_504() -> None:
    with (
        patch("case_api.main.evaluate_workflows", new_callable=AsyncMock),
        patch(
            "case_api.sar_transport_monitor_api.process_sar_transport_once", new_callable=AsyncMock
        ) as proc,
    ):
        from case_api.main import app

        proc.side_effect = TimeoutError("SFTP handshake timed out")
        with TestClient(app) as client:
            r = client.post("/v1/cases/ops/sar-transport/force-sftp-sync", headers=_api_headers())
    assert r.status_code == 504
    body = r.json()
    assert body.get("error", {}).get("code") == "sftp_timeout" or "504" in str(body)


def test_force_sftp_sync_maps_paramiko_ssh_exception_to_502() -> None:
    paramiko = pytest.importorskip(
        "paramiko", reason="paramiko is a case-api dependency; install deps for this service venv."
    )

    with (
        patch("case_api.main.evaluate_workflows", new_callable=AsyncMock),
        patch(
            "case_api.sar_transport_monitor_api.process_sar_transport_once", new_callable=AsyncMock
        ) as proc,
    ):
        from case_api.main import app

        proc.side_effect = paramiko.SSHException("connection failed")
        with TestClient(app) as client:
            r = client.post("/v1/cases/ops/sar-transport/force-sftp-sync", headers=_api_headers())
    assert r.status_code == 502
    body = r.json()
    assert body.get("error", {}).get("code") == "sftp_ssh_error" or "502" in str(body)
