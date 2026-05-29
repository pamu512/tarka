"""Gate: NATS shadow.investigate worker calls ShadowAgent.evaluate with audit persistence."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

_SRC = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_handle_shadow_investigate_payload_invokes_evaluate() -> None:
    import tarka_shared.audit_trail  # noqa: F401, PLC0415

    from ingestor.schemas import TransactionSchema  # noqa: E402
    from shadow_agent.agent import ShadowAgent  # noqa: E402
    from shadow_agent.schemas import ShadowDecision  # noqa: E402
    from shadow_agent.workers.shadow_investigate_handler import (
        handle_shadow_investigate_payload,
    )  # noqa: E402
    from shadow_agent.workers.runtime import ShadowInvestigateRuntime  # noqa: E402
    from tarka_shared.audit_trail import AuditLog  # noqa: E402

    entity = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    tx = TransactionSchema(
        entity_id=entity,
        amount=42.0,
        timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        metadata={"user_id": "u_worker_gate"},
    )
    payload = {
        "session_id": "sess-worker-1",
        "entity_id": str(entity),
        "trace": [{"rule_id": "r1", "matched": True}],
        "transaction": tx.model_dump(mode="json"),
    }

    mock_agent = MagicMock(spec=ShadowAgent)
    decision = ShadowDecision(
        transaction_id=entity,
        risk_score=12.0,
        is_fraud=False,
        reasoning=["ok"],
        confidence_metrics={"confidence": 0.99},
        ai_reasoning="clear",
    )
    audit = AuditLog(
        case_id=str(entity),
        action_taken="{}",
        code_executed=None,
        agent_notes="{}",
    )
    audit.id = 77
    mock_agent.evaluate = AsyncMock(return_value=(decision, audit))

    async def _run_gateway(coro: object) -> object:
        assert callable(coro)
        return await coro()  # type: ignore[misc]

    gateway = MagicMock()
    gateway.run_shadow_investigate_inference = AsyncMock(side_effect=_run_gateway)

    session = AsyncMock()
    session.in_transaction.return_value = False
    session_factory = MagicMock(return_value=session)

    runtime = ShadowInvestigateRuntime(
        gateway=gateway,
        agent=mock_agent,
        session_factory=session_factory,
        engine=MagicMock(),
        llm_client=MagicMock(),
    )

    ok = asyncio.run(handle_shadow_investigate_payload(runtime, payload))
    assert ok is True
    mock_agent.evaluate.assert_awaited_once()
    _args, kwargs = mock_agent.evaluate.await_args
    assert _args[0].entity_id == entity
    assert kwargs["graph_context"] == {"evaluation_trace": payload["trace"]}
    gateway.run_shadow_investigate_inference.assert_awaited_once()


def test_handle_shadow_investigate_payload_skips_legacy_body_without_transaction() -> None:
    from shadow_agent.workers.shadow_investigate_handler import (
        handle_shadow_investigate_payload,
    )  # noqa: E402
    from shadow_agent.workers.runtime import ShadowInvestigateRuntime  # noqa: E402

    gateway = MagicMock()
    gateway.run_shadow_investigate_inference = AsyncMock()
    runtime = ShadowInvestigateRuntime(
        gateway=gateway,
        agent=MagicMock(),
        session_factory=MagicMock(),
        engine=MagicMock(),
        llm_client=MagicMock(),
    )
    ok = asyncio.run(
        handle_shadow_investigate_payload(
            runtime,
            {"session_id": "legacy-only", "trace": []},
        ),
    )
    assert ok is False
    gateway.run_shadow_investigate_inference.assert_not_awaited()
