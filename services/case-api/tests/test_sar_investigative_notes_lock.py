"""SAR intent investigative notes: server-side lock when Uploaded (TRANSMITTED / ACKNOWLEDGED)."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

from case_api.db import SessionLocal
from case_api.models import Case, SARFiling, SarFiling
from case_api.sar_transport import SAR_APPROVED, SAR_TRANSMITTED
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


def test_patch_investigative_notes_rejected_when_uploaded() -> None:
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        tid = "tenant-sar-notes-lock"
        case_id = uuid.uuid4()
        art_id = uuid.uuid4()
        intent_id = uuid.uuid4()

        import asyncio

        async def seed() -> None:
            async with SessionLocal() as session, session.begin():
                session.add(
                    Case(
                        id=case_id,
                        tenant_id=tid,
                        title="sar-lock",
                        status="open",
                        entity_id="e1",
                        trace_id="tr-lock-1",
                    )
                )
                session.add(
                    SARFiling(
                        id=art_id,
                        case_id=case_id,
                        format="fincen_xml",
                        status="draft",
                        narrative="n",
                        report_data={"report_id": "R1"},
                        xml_content="<EFilingBatchXML><test/></EFilingBatchXML>",
                    )
                )
                session.add(
                    SarFiling(
                        id=intent_id,
                        tenant_id=tid,
                        case_id=case_id,
                        sar_artifact_id=art_id,
                        status=SAR_TRANSMITTED,
                        filing_data={},
                        audit_trail={},
                        investigative_notes_html="<p>Prior</p>",
                    )
                )

        with TestClient(app) as client:
            asyncio.run(seed())
            r = client.patch(
                f"/v1/cases/{case_id}/sar/intents/{intent_id}/investigative-notes",
                params={"tenant_id": tid},
                headers=_api_headers(),
                json={"notes_html": "<p>Bypass attempt</p>"},
            )
        assert r.status_code == 403, r.text
        assert "sar_notes_locked" in r.text or "read-only" in r.text.lower()


def test_patch_investigative_notes_ok_when_not_uploaded() -> None:
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        tid = "tenant-sar-notes-open"
        case_id = uuid.uuid4()
        art_id = uuid.uuid4()
        intent_id = uuid.uuid4()

        import asyncio

        async def seed() -> None:
            async with SessionLocal() as session, session.begin():
                session.add(
                    Case(
                        id=case_id,
                        tenant_id=tid,
                        title="sar-open",
                        status="open",
                        entity_id="e1",
                        trace_id="tr-open-1",
                    )
                )
                session.add(
                    SARFiling(
                        id=art_id,
                        case_id=case_id,
                        format="fincen_xml",
                        status="draft",
                        narrative="n",
                        report_data={"report_id": "R1"},
                        xml_content="<EFilingBatchXML/>",
                    )
                )
                session.add(
                    SarFiling(
                        id=intent_id,
                        tenant_id=tid,
                        case_id=case_id,
                        sar_artifact_id=art_id,
                        status=SAR_APPROVED,
                        filing_data={},
                        audit_trail={},
                        investigative_notes_html="",
                    )
                )

        with TestClient(app) as client:
            asyncio.run(seed())
            r = client.patch(
                f"/v1/cases/{case_id}/sar/intents/{intent_id}/investigative-notes",
                params={"tenant_id": tid},
                headers=_api_headers(),
                json={"notes_html": "<p><strong>Hello</strong></p>"},
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert "<strong>Hello</strong>" in data.get(
            "investigative_notes_html", ""
        ) or "Hello" in data.get("investigative_notes_html", "")


def test_get_detail_includes_sha_when_transmitted() -> None:
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        tid = "tenant-sar-detail-sha"
        case_id = uuid.uuid4()
        art_id = uuid.uuid4()
        intent_id = uuid.uuid4()

        import asyncio

        async def seed() -> None:
            async with SessionLocal() as session, session.begin():
                session.add(
                    Case(
                        id=case_id,
                        tenant_id=tid,
                        title="sar-sha",
                        status="open",
                        entity_id="e1",
                        trace_id="tr-sha-1",
                    )
                )
                session.add(
                    SARFiling(
                        id=art_id,
                        case_id=case_id,
                        format="fincen_xml",
                        status="draft",
                        narrative="n",
                        report_data={"report_id": "R1"},
                        xml_content="<X/>",
                    )
                )
                session.add(
                    SarFiling(
                        id=intent_id,
                        tenant_id=tid,
                        case_id=case_id,
                        sar_artifact_id=art_id,
                        status=SAR_TRANSMITTED,
                        filing_data={},
                        audit_trail={},
                        investigative_notes_html="",
                    )
                )

        with TestClient(app) as client:
            asyncio.run(seed())
            r = client.get(
                f"/v1/cases/{case_id}/sar/intents/{intent_id}/detail",
                params={"tenant_id": tid},
                headers=_api_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("notes_editor_locked") is True
        sha = body.get("fincen_submission_sha256_hex")
        assert isinstance(sha, str) and len(sha) == 64
