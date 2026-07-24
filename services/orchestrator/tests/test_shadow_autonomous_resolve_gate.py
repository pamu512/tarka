"""Gate: Shadow autoresolve hook is disabled (AI never changes case status)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_maybe_autoresolve_lifecycle_case_disabled_even_at_high_confidence() -> None:
    from shadow.hooks.resolve_case import (
        CONFIDENCE_THRESHOLD,
        maybe_autoresolve_lifecycle_case,
    )

    async def _run() -> None:
        out = await maybe_autoresolve_lifecycle_case(
            orchestrator_base_url="http://testserver",
            case_id="case-1",
            confidence=min(1.0, CONFIDENCE_THRESHOLD + 0.04),
            auth_token="shadow-agent-gate",
        )
        assert out.called_api is False
        assert out.skipped_reason == "ai_autoresolve_disabled"
        assert out.http_status is None

    asyncio.run(_run())


def test_autoresolve_skipped_when_confidence_at_threshold() -> None:
    from shadow.hooks.resolve_case import (
        CONFIDENCE_THRESHOLD,
        maybe_autoresolve_lifecycle_case,
    )

    async def _run() -> None:
        out = await maybe_autoresolve_lifecycle_case(
            orchestrator_base_url="http://testserver",
            case_id="case-2",
            confidence=CONFIDENCE_THRESHOLD,
            auth_token="tok",
        )
        assert out.called_api is False
        assert out.skipped_reason == "ai_autoresolve_disabled"

    asyncio.run(_run())
