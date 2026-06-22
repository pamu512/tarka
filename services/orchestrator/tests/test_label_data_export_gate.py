"""Gate: GET /v1/labels/export streaming ML dataset export."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_AUTH_HEADERS = {"X-Auth-Token": "gate-label-export-token"}
_ENTITY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_parse_export_window_inclusive_dates() -> None:
    from services.label_data_export import parse_export_window

    window = parse_export_window(start_date="2026-05-01", end_date="2026-05-03")
    assert window.start == datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    assert window.end.date().isoformat() == "2026-05-03"


def test_parse_export_format_defaults_to_jsonl() -> None:
    from services.label_data_export import LabelExportFormat, parse_export_format

    assert parse_export_format(None) == LabelExportFormat.JSONL
    assert parse_export_format("json") == LabelExportFormat.JSON


def test_label_export_stream_deduplicates_normalized_labels_by_source() -> None:
    async def _run() -> None:
        import models.normalized_labels  # noqa: F401
        import models.operational_signals  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from models.normalized_labels import (
            GroundTruthClass,
            NormalizedLabelDAO,
            NormalizedLabelORM,
        )
        from models.operational_signals import OperationalSignalDAO
        from schemas.operational_signals import SignalType
        from services.label_data_export import (
            iter_label_export_records,
            parse_export_window,
        )
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        source_id = uuid.uuid4()
        async with fac() as session:
            async with session.begin():
                session.add(
                    NormalizedLabelORM(
                        source_type="ANALYST_DISPOSITION",
                        source_id=source_id,
                        entity_id=_ENTITY_ID,
                        ground_truth_class=GroundTruthClass.FRAUD.value,
                        tags=["analyst_disposition"],
                        propagated_to_consortium=False,
                        created_at=datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC),
                    ),
                )
                session.add(
                    NormalizedLabelORM(
                        source_type="ANALYST_DISPOSITION",
                        source_id=source_id,
                        entity_id=_ENTITY_ID,
                        ground_truth_class=GroundTruthClass.FRAUD.value,
                        tags=["analyst_disposition", "vector:chargeback"],
                        propagated_to_consortium=True,
                        created_at=datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC),
                    ),
                )
                signal_row = await OperationalSignalDAO.create(
                    session,
                    idempotency_key="cb:entity-1:4853",
                    target_entity_id=_ENTITY_ID,
                    signal_type=SignalType.CHARGEBACK_RECEIVED,
                    metadata={
                        "amount_cents": 1000,
                        "currency": "USD",
                        "chargeback_reason_code": "4853",
                        "card_network": "VISA",
                    },
                )
                signal_row.created_at = datetime(2026, 5, 2, 14, 0, 0, tzinfo=UTC)

        window = parse_export_window(start_date="2026-05-01", end_date="2026-05-31")
        rows = [row async for row in iter_label_export_records(fac, window=window)]
        assert len(rows) == 2
        assert {row["record_type"] for row in rows} == {"normalized_label", "operational_signal"}
        label_rows = [row for row in rows if row["record_type"] == "normalized_label"]
        assert len(label_rows) == 1
        assert "vector:chargeback" in label_rows[0]["tags"]
        assert label_rows[0]["dedupe_key"] == f"normalized_label:ANALYST_DISPOSITION:{source_id}"

        await engine.dispose()

    asyncio.run(_run())


def test_get_labels_export_jsonl_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import models.normalized_labels  # noqa: F401, PLC0415
    import models.operational_signals  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from deps.v1_api_guard import V1_PROTECTED_ROUTE_DEPENDENCIES
    from models.normalized_labels import (
        GroundTruthClass,
        NormalizedLabelORM,
    )  # noqa: E402
    from routes.data_export import router as data_export_router
    from tarka_shared.database.session import Base  # noqa: E402

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            async with session.begin():
                session.add(
                    NormalizedLabelORM(
                        source_type="ANALYST_DISPOSITION",
                        source_id=uuid.uuid4(),
                        entity_id=_ENTITY_ID,
                        ground_truth_class=GroundTruthClass.LEGITIMATE.value,
                        tags=["analyst_disposition"],
                        propagated_to_consortium=True,
                        created_at=datetime(2026, 5, 10, 8, 0, 0, tzinfo=UTC),
                    ),
                )
        return fac

    fac = asyncio.run(_setup())
    app = FastAPI()
    app.state.audit_session_factory = fac
    app.state.v1_rate_limiter = None
    app.include_router(
        data_export_router, prefix="/v1", dependencies=V1_PROTECTED_ROUTE_DEPENDENCIES
    )

    with TestClient(app) as client:
        r = client.get(
            "/v1/labels/export",
            params={"start_date": "2026-05-01", "end_date": "2026-05-31"},
            headers=_AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/x-ndjson")
        lines = [ln for ln in r.text.strip().splitlines() if ln.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["schema"] == "tarka.label_export.v1"
        assert row["record_type"] == "normalized_label"
        assert row["ground_truth_class"] == "LEGITIMATE"

    asyncio.run(engine.dispose())
