#!/usr/bin/env python3
"""Unit tests for demo vertical response shapes (stdlib only; run: python3 scripts/ci/test_demo_vertical_contracts.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

_ci = Path(__file__).resolve().parent
if str(_ci) not in sys.path:
    sys.path.insert(0, str(_ci))

from demo_vertical_contracts import (
    check_create_case_response,
    check_evaluate_response,
    check_event_ingest_accepted,
    check_frontend_reachable,
)


class TestDemoVerticalContracts(unittest.TestCase):
    def test_evaluate_minimal(self) -> None:
        tid = str(uuid4())
        check_evaluate_response(
            {
                "decision": "allow",
                "score": 12.3,
                "trace_id": tid,
                "tags": [],
                "rule_hits": [],
                "reasons": [],
                "inference_context": {"schema_version": "3", "calibration_profile": "default"},
            }
        )

    def test_case_create_minimal(self) -> None:
        check_create_case_response(
            {
                "id": str(uuid4()),
                "tenant_id": "t1",
                "title": "x",
                "entity_id": "e1",
                "trace_id": str(uuid4()),
                "status": "open",
                "priority": "low",
                "labels": [],
            }
        )

    def test_ingest_status(self) -> None:
        check_event_ingest_accepted(200)
        with self.assertRaises(AssertionError):
            check_event_ingest_accepted(503)

    def test_frontend_reachable(self) -> None:
        check_frontend_reachable(200)
        with self.assertRaises(AssertionError):
            check_frontend_reachable(500)


if __name__ == "__main__":
    unittest.main()
