"""Unit tests: velocity key layout + bucket alignment."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_velocity_bucket_alignment() -> None:
    from anumana_velocity import velocity_bucket

    assert velocity_bucket(60, 120) == 2
    assert velocity_bucket(300, 600) == 2
    assert velocity_bucket(3600, 7200) == 2
