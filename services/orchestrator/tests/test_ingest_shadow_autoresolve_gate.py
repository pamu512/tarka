"""Unit gate: Shadow autoresolve is disabled (AI must not change case status)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_try_shadow_autoresolve_after_ingest_is_disabled() -> None:
    async def _run() -> None:
        from shadow_autoresolve import try_shadow_autoresolve_after_ingest
        from shadow.hooks.resolve_case import CONFIDENCE_THRESHOLD

        entity_id = str(uuid4())
        shadow_data = {
            "transaction_id": entity_id,
            "risk_score": 6.0,
            "is_fraud": False,
            "reasoning": ["pattern ok"],
            "confidence_metrics": {
                "confidence": min(1.0, CONFIDENCE_THRESHOLD + 0.02),
                "recommended_action": "AUTO_RESOLVE",
            },
            "ai_reasoning": "Machine cleared: benign merchant history.",
        }

        out = await try_shadow_autoresolve_after_ingest(
            audit_session_factory=None,  # type: ignore[arg-type]
            graph_client=None,
            audit_log_id=1,
            entity_id=entity_id,
            metadata={"user_id": "u"},
            actions=["ALLOW"],
            rule_data={"actions": ["ALLOW"]},
            shadow_data=shadow_data,
            auth_token="inline-autoresolve-token",
            lifecycle_actions=["FLAG"],
        )

        assert out.attempted is False
        assert out.lifecycle_case_id is None
        assert out.transition is None
        assert out.skipped_reason == "ai_autoresolve_disabled"

    asyncio.run(_run())


def test_shadow_autoresolve_eligible_always_disabled() -> None:
    from shadow.hooks.resolve_case import (
        CONFIDENCE_THRESHOLD,
        shadow_autoresolve_eligible,
    )

    ok, conf, skip = shadow_autoresolve_eligible(
        {
            "is_fraud": False,
            "risk_score": 5.0,
            "confidence_metrics": {"confidence": CONFIDENCE_THRESHOLD + 0.01},
        },
    )
    assert ok is False
    assert skip == "ai_autoresolve_disabled"
    assert conf is not None
