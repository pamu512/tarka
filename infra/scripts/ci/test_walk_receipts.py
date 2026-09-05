#!/usr/bin/env python3
"""Offline tests for the clone-and-run receipt walk (stdlib).

Run: PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
_OSS = _REPO / "scripts" / "oss"
if str(_OSS) not in sys.path:
    sys.path.insert(0, str(_OSS))

import walk_receipts  # noqa: E402


class TestWalkCases(unittest.TestCase):
    def test_three_distinct_entities_no_invented_decisions(self) -> None:
        cases = walk_receipts.WALK_CASES
        self.assertGreaterEqual(len(cases), 3)
        entities = [c["body"]["entity_id"] for c in cases]
        self.assertEqual(len(entities), len(set(entities)))
        for case in cases:
            self.assertNotIn("expected_decision", case)
            self.assertNotIn("decision", case)
            body = case["body"]
            self.assertEqual(body["tenant_id"], "demo")
            self.assertTrue(body["entity_id"])
            self.assertEqual(body["event_type"], "payment")
            self.assertIn("payload", body)

    def test_cases_exercise_shipped_pack_fields(self) -> None:
        labels = {c["label"] for c in walk_receipts.WALK_CASES}
        self.assertIn("clean_payment", labels)
        self.assertTrue(labels & {"bot_signal", "bot_and_vpn"})
        signals: list[dict[str, Any]] = []
        for case in walk_receipts.WALK_CASES:
            dc = case["body"].get("device_context") or {}
            sig = dc.get("signals") or {}
            if sig:
                signals.append(sig)
        keys = {k for sig in signals for k in sig}
        self.assertTrue(keys & {"is_bot", "is_vpn", "is_repackaged", "is_emulator"})

    def test_no_investor_theater_copy(self) -> None:
        blob = repr(walk_receipts.WALK_CASES).lower()
        for banned in ("allow $42", "demo-burst", "arr", "customer"):
            self.assertNotIn(banned, blob)


class TestHonestCopy(unittest.TestCase):
    def test_looking_at_is_five_honest_lines(self) -> None:
        lines = walk_receipts.looking_at_lines()
        self.assertEqual(len(lines), 5)
        joined = "\n".join(lines).lower()
        self.assertIn("pack", joined)
        self.assertIn("receipt", joined)
        self.assertIn("observe", joined)
        self.assertIn("graph_service_url", joined)
        self.assertTrue("hop" in joined or "edge" in joined)
        self.assertNotIn("open source", joined)
        self.assertNotIn("vertex", joined)

    def test_desk_urls_point_at_local_desk(self) -> None:
        urls = walk_receipts.desk_urls()
        blob = " ".join(urls.values())
        self.assertIn("http://127.0.0.1:3000", blob)
        self.assertIn("/graph", blob)
        self.assertIn("/decisions", blob)
        self.assertIn("/ops/shadow", blob)

    def test_format_receipt_includes_why_and_entity(self) -> None:
        line = walk_receipts.format_receipt(
            label="clean_payment",
            entity_id="clone-demo-clean",
            decision="allow",
            score=10.0,
            trace_id="tr-1",
            reasons=["rules:"],
            rule_hits=["high_amount_payment"],
        )
        self.assertIn("allow", line.lower())
        self.assertIn("clone-demo-clean", line)
        self.assertIn("tr-1", line)
        self.assertIn("high_amount_payment", line)

    def test_summarize_only_allow_is_honest(self) -> None:
        text = walk_receipts.summarize_outcomes(["allow", "allow", "allow"])
        low = text.lower()
        self.assertIn("allow", low)
        self.assertNotIn("review", low)
        self.assertNotIn("deny", low)
        self.assertTrue("only" in low or "same" in low or "single" in low)

    def test_summarize_mixed_lists_what_evaluate_returned(self) -> None:
        text = walk_receipts.summarize_outcomes(["allow", "review", "deny"])
        low = text.lower()
        self.assertIn("allow", low)
        self.assertIn("review", low)
        self.assertIn("deny", low)


class TestWalkRunner(unittest.TestCase):
    def test_run_walk_prints_returned_decisions_not_invented(self) -> None:
        canned = {
            "clone-demo-clean": {
                "trace_id": "t-clean",
                "decision": "allow",
                "score": 10.0,
                "reasons": [],
                "rule_hits": [],
            },
            "clone-demo-bot": {
                "trace_id": "t-bot",
                "decision": "review",
                "score": 75.0,
                "reasons": ["rules:sdk_bot"],
                "rule_hits": ["sdk_bot"],
            },
            "clone-demo-bot-vpn": {
                "trace_id": "t-deny",
                "decision": "deny",
                "score": 90.0,
                "reasons": ["rules:sdk_bot,sdk_vpn"],
                "rule_hits": ["sdk_bot", "sdk_vpn"],
            },
        }

        def fake_request(
            method: str,
            url: str,
            *,
            payload: dict[str, Any] | None = None,
            api_key: str | None = None,
            timeout: float = 30.0,
        ) -> tuple[int, Any]:
            if method == "GET" and url.endswith("/v1/health"):
                return 200, {"status": "ok"}
            if method == "POST" and payload:
                entity = str(payload.get("entity_id") or "")
                if entity in canned:
                    return 200, canned[entity]
            return 404, {}

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = walk_receipts.run_walk(
                request=fake_request,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("allow", out.lower())
        self.assertIn("review", out.lower())
        self.assertIn("deny", out.lower())
        self.assertIn("http://127.0.0.1:3000", out)
        self.assertIn("/decisions", out)
        self.assertIn("NEXT: http://127.0.0.1:3000/graph?entity_id=clone-demo-bot-vpn", out)
        self.assertNotIn("ALLOW $42", out)
        self.assertNotIn("Unit21", out)
        self.assertNotIn("Sardine", out)

    def test_run_walk_fails_closed_on_bad_health(self) -> None:
        def fake_request(method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
            return 0, "connection refused"

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = walk_receipts.run_walk(
                request=fake_request,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
