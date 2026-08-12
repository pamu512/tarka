"""Bot detection must not invent likelihood scores."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SIDECAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SIDECAR))

from onnx_engine import BotDetectionModel, BotDetectionUnavailable  # noqa: E402


def test_bot_detection_refuses_placeholder_score() -> None:
    bot = BotDetectionModel()

    async def _run() -> None:
        with pytest.raises(BotDetectionUnavailable, match="refusing invented"):
            await bot.predict(42.0)

    asyncio.run(_run())
