"""Unit tests for /v1/replay trace_ids mode and response shape."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from decision_api.replay import ReplayRequest, ReplayRule, ReplayCondition, replay_events


def _audit_row(*, trace_id, tenant_id="t1", entity_id="e1", decision="allow", score=40.0, payload=None):
    row = MagicMock()
    row.trace_id = trace_id
    row.tenant_id = tenant_id
    row.entity_id = entity_id
    row.event_type = "payment"
    row.decision = decision
    row.score = score
    row.rule_hits = []
    row.payload_snapshot = payload or {"payload": {"amount": 50}, "metadata": {}}
    return row


@pytest.mark.asyncio
async def test_replay_trace_ids_preserves_order_and_reports_missing():
    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    u_missing = uuid.uuid4()
    rec1 = _audit_row(trace_id=u1, score=30.0)
    rec2 = _audit_row(trace_id=u2, score=60.0)

    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [rec2, rec1]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=exec_result)

    body = ReplayRequest(
        tenant_id="t1",
        rules_override=[
            ReplayRule(
                id="r1",
                when=[ReplayCondition(field="amount", op="gte", value=0)],
                score_delta=5.0,
            )
        ],
        trace_ids=[str(u1), str(u_missing), str(u2)],
    )

    out = await replay_events(body, session)

    assert out.tenant_id == "t1"
    assert out.events_evaluated == 2
    assert out.missing_trace_ids == [str(u_missing)]
    assert [r.trace_id for r in out.results] == [str(u1), str(u2)]


@pytest.mark.asyncio
async def test_replay_limit_mode_empty_audits_404():
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)

    body = ReplayRequest(
        tenant_id="t1",
        rules_override=[
            ReplayRule(when=[ReplayCondition(field="amount", op="gte", value=0)], score_delta=0)
        ],
        limit=10,
        trace_ids=[],
    )

    with pytest.raises(HTTPException) as exc:
        await replay_events(body, session)
    assert exc.value.status_code == 404
    session.execute.assert_called_once()
