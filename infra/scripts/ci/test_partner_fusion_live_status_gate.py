#!/usr/bin/env python3
"""Self-test for partner_fusion_live_status_gate (stdlib unittest)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO / "scripts" / "oss"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from partner_fusion_live_status_gate import evaluate  # noqa: E402


class TestLiveStatusGate(unittest.TestCase):
    def test_waived_ok(self) -> None:
        code, _ = evaluate(
            status_text="WAIVED — reason: no live vendor credentials in OSS CI\n",
            live_sha_text="",
            require_live=True,
        )
        self.assertEqual(code, 0)

    def test_live_without_sha_fails(self) -> None:
        code, msg = evaluate(
            status_text="LIVE\n",
            live_sha_text="",
            require_live=True,
        )
        self.assertEqual(code, 1)
        self.assertIn("sha256", msg.lower())

    def test_live_with_sha_ok(self) -> None:
        code, _ = evaluate(
            status_text="LIVE\n",
            live_sha_text="abc123\n",
            require_live=True,
        )
        self.assertEqual(code, 0)

    def test_invalid_fails(self) -> None:
        code, _ = evaluate(
            status_text="fixture-is-fine\n",
            live_sha_text="abc",
            require_live=True,
        )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
