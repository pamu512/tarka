"""SAR regulatory state machine + worker failure paths (SQLite in-memory)."""

from __future__ import annotations

import uuid

import pytest
from case_api.db import SessionLocal, init_db
from case_api.models import Case, SarAuditLog, SARFiling, SarFiling
from case_api.sar_transport import (
    SAR_APPROVED,
    SAR_FAILED,
    SAR_PENDING_REVIEW,
    SAR_SFTP_QUEUED,
    record_sar_intent_initial_state,
    transition_sar_intent,
)
from case_api.sar_transport_worker import process_sar_transport_once
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_sar_intent_transition_writes_audit_log() -> None:
    await init_db()
    case_id = uuid.uuid4()
    filing_id = uuid.uuid4()
    intent_id = uuid.uuid4()

    async with SessionLocal() as session:
        async with session.begin():
            session.add(
                Case(
                    id=case_id,
                    tenant_id="t1",
                    title="c",
                    status="open",
                    entity_id="e1",
                    trace_id="tr1",
                )
            )
            session.add(
                SARFiling(
                    id=filing_id,
                    case_id=case_id,
                    format="fincen_xml",
                    status="draft",
                    narrative="n",
                    report_data={"report_id": "R1"},
                    xml_content="<EFilingBatchXML/>",
                )
            )
            intent = SarFiling(
                id=intent_id,
                tenant_id="t1",
                case_id=case_id,
                sar_artifact_id=filing_id,
                status=SAR_PENDING_REVIEW,
                filing_data={"sar_artifact_id": str(filing_id)},
                audit_trail={},
            )
            session.add(intent)
            await session.flush()
            await record_sar_intent_initial_state(
                session, intent, actor="analyst", detail={"note": "created"}
            )

    async with SessionLocal() as session:
        intent = await session.get(SarFiling, intent_id)
        assert intent is not None
        await transition_sar_intent(
            session,
            intent,
            to_status=SAR_APPROVED,
            actor="compliance",
            detail={"reason_code": "SAR_APPROVED"},
        )
        await session.commit()

    async with SessionLocal() as session:
        n = await session.scalar(select(func.count()).select_from(SarAuditLog))
        assert int(n or 0) >= 2


@pytest.mark.asyncio
async def test_worker_fails_sftp_queued_when_host_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    await init_db()
    monkeypatch.setenv("FINCEN_BSA_SFTP_HOST", "")
    from case_api import config

    monkeypatch.setattr(config.settings, "fincen_bsa_sftp_host", "", raising=False)

    case_id = uuid.uuid4()
    filing_id = uuid.uuid4()
    intent_id = uuid.uuid4()

    async with SessionLocal() as session:
        async with session.begin():
            session.add(
                Case(
                    id=case_id,
                    tenant_id="t1",
                    title="c",
                    status="open",
                    entity_id="e1",
                    trace_id="tr1",
                )
            )
            session.add(
                SARFiling(
                    id=filing_id,
                    case_id=case_id,
                    format="fincen_xml",
                    status="draft",
                    narrative="n",
                    report_data={"report_id": "R1"},
                    xml_content="<EFilingBatchXML/>",
                )
            )
            intent = SarFiling(
                id=intent_id,
                tenant_id="t1",
                case_id=case_id,
                sar_artifact_id=filing_id,
                status=SAR_PENDING_REVIEW,
                filing_data={"sar_artifact_id": str(filing_id)},
                audit_trail={},
            )
            session.add(intent)
            await session.flush()
            await record_sar_intent_initial_state(
                session, intent, actor="test", detail={"bootstrap": True}
            )
            await transition_sar_intent(
                session, intent, to_status=SAR_APPROVED, actor="test", detail={}
            )
            await transition_sar_intent(
                session, intent, to_status=SAR_SFTP_QUEUED, actor="test", detail={}
            )

    processed = await process_sar_transport_once()
    assert processed is True

    async with SessionLocal() as session:
        intent = await session.get(SarFiling, intent_id)
        assert intent is not None
        assert intent.status == SAR_FAILED
