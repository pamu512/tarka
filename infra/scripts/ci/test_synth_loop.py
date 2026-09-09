#!/usr/bin/env python3
"""Offline tests for the local synth-loop operator tool (stdlib).

Mocks HTTP. No live stack. Run:

  PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_synth_loop.py
"""

from __future__ import annotations

import io
import sys
import unittest
from argparse import ArgumentParser
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
_OSS = _REPO / "scripts" / "oss"
if str(_OSS) not in sys.path:
    sys.path.insert(0, str(_OSS))

import synth_loop  # noqa: E402
import walk_receipts  # noqa: E402


class TestHelpAndFlags(unittest.TestCase):
    def test_parser_is_argparse_with_expected_flags(self) -> None:
        parser = synth_loop.build_parser()
        self.assertIsInstance(parser, ArgumentParser)
        text = parser.format_help()
        for flag in ("--interval", "--max", "--label-every", "--tenant", "--dry-run"):
            self.assertIn(flag, text)
        args = parser.parse_args([])
        self.assertEqual(args.interval, 2.0)
        self.assertEqual(args.max, 0)
        self.assertEqual(args.label_every, 10)
        self.assertEqual(args.tenant, "demo")
        self.assertFalse(args.dry_run)

    def test_main_help_exits_zero(self) -> None:
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = synth_loop.main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--interval", buf.getvalue() + err.getvalue())


class TestCasesHonesty(unittest.TestCase):
    def test_cases_mirror_walk_and_add_no_invented_decisions(self) -> None:
        cases = synth_loop.SYNTH_CASES
        self.assertGreaterEqual(len(cases), len(walk_receipts.WALK_CASES))
        walk_labels = {c["label"] for c in walk_receipts.WALK_CASES}
        synth_labels = {c["label"] for c in cases}
        self.assertTrue(walk_labels <= synth_labels)
        for case in cases:
            self.assertNotIn("expected_decision", case)
            self.assertNotIn("decision", case)
            body = case["body"]
            self.assertTrue(body.get("entity_id"))
            self.assertIn("event_type", body)
            self.assertIn("payload", body)

    def test_source_has_no_llm_keys_or_sku_copy(self) -> None:
        text = (_OSS / "synth_loop.py").read_text(encoding="utf-8").lower()
        for banned in (
            "openai_api_key",
            "shadow_llm_api_key",
            "sk-",
            "continuous synth sku",
        ):
            self.assertNotIn(banned, text)


class TestPayloadBuilders(unittest.TestCase):
    def test_evaluate_body_rotates_entity_device_amount_event(self) -> None:
        bodies = [
            synth_loop.build_evaluate_body(tick=i, tenant="acme") for i in range(8)
        ]
        entities = [b["entity_id"] for b in bodies]
        amounts = [b["payload"]["amount"] for b in bodies]
        events = [b["event_type"] for b in bodies]
        devices = [
            (b.get("device_context") or {}).get("device_id")
            for b in bodies
            if (b.get("device_context") or {}).get("device_id")
        ]
        self.assertGreater(len(set(entities)), 1)
        self.assertGreater(len(set(amounts)), 1)
        self.assertGreater(len(set(events)), 1)
        self.assertGreater(len(set(devices)), 1)
        for body in bodies:
            self.assertEqual(body["tenant_id"], "acme")
            self.assertNotIn("expected_decision", body)

    def test_label_payload_prefers_evaluation_token(self) -> None:
        payload = synth_loop.build_label_payload(
            {
                "evaluation_token": "tok-1",
                "trace_id": "tr-1",
                "tenant_id": "ignored",
            },
            tenant="demo",
            label_kind="fp",
        )
        self.assertEqual(payload["evaluation_token"], "tok-1")
        self.assertEqual(payload["tenant_id"], "demo")
        self.assertEqual(payload["label_kind"], "fp")
        self.assertNotIn("trace_id", payload)

    def test_label_payload_falls_back_to_trace_and_tenant(self) -> None:
        payload = synth_loop.build_label_payload(
            {"trace_id": "tr-9"},
            tenant="demo",
            label_kind="fraud",
        )
        self.assertEqual(payload["trace_id"], "tr-9")
        self.assertEqual(payload["tenant_id"], "demo")
        self.assertEqual(payload["label_kind"], "fraud")
        self.assertNotIn("evaluation_token", payload)


class TestRunLoopMockHttp(unittest.TestCase):
    def test_dry_run_prints_payloads_without_http(self) -> None:
        calls: list[str] = []

        def fake_request(*_a: Any, **_k: Any) -> tuple[int, Any]:
            calls.append("hit")
            return 500, {"nope": True}

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = synth_loop.run_loop(
                request=fake_request,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
                interval=0.0,
                max_events=2,
                label_every=1,
                tenant="demo",
                dry_run=True,
                sleeper=lambda _s: None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        out = buf.getvalue()
        self.assertIn("/v1/decisions/evaluate", out)
        self.assertIn("entity_id", out)
        self.assertIn("dry-run", out.lower())

    def test_loop_prints_honest_receipt_and_labels_every_n(self) -> None:
        posts: list[tuple[str, dict[str, Any] | None]] = []

        def fake_request(
            method: str,
            url: str,
            *,
            payload: dict[str, Any] | None = None,
            api_key: str | None = None,
            timeout: float = 30.0,
            extra_headers: dict[str, str] | None = None,
        ) -> tuple[int, Any]:
            posts.append((url, payload))
            self.assertEqual(api_key, "k-test")
            if method == "POST" and url.endswith("/v1/decisions/evaluate"):
                entity = str((payload or {}).get("entity_id") or "e")
                return 200, {
                    "trace_id": f"tr-{entity}",
                    "evaluation_token": f"tok-{entity}",
                    "decision": "review",
                    "score": 75.0,
                    "reasons": ["rules:sdk_bot"],
                    "rule_hits": ["sdk_bot"],
                }
            if method == "POST" and url.endswith("/v1/webhooks/late-label"):
                return 200, {"ok": True, "label_kind": (payload or {}).get("label_kind")}
            return 404, {}

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = synth_loop.run_loop(
                request=fake_request,
                base="http://127.0.0.1:8000/decisions",
                api_key="k-test",
                interval=0.0,
                max_events=3,
                label_every=2,
                tenant="demo",
                dry_run=False,
                sleeper=lambda _s: None,
            )
        self.assertEqual(code, 0)
        evals = [p for u, p in posts if u.endswith("/v1/decisions/evaluate")]
        labels = [p for u, p in posts if u.endswith("/v1/webhooks/late-label")]
        self.assertEqual(len(evals), 3)
        self.assertEqual(len(labels), 1)
        self.assertIn((labels[0] or {}).get("label_kind"), {"fp", "fraud"})
        self.assertTrue((labels[0] or {}).get("evaluation_token"))
        out = buf.getvalue()
        self.assertIn("review", out.lower())
        self.assertIn("sdk_bot", out)
        self.assertIn("entity_id=", out)
        self.assertNotIn("ALLOW $42", out)
        self.assertNotIn("Unit21", out)

    def test_label_bind_failure_is_soft(self) -> None:
        n_eval = 0

        def fake_request(
            method: str,
            url: str,
            *,
            payload: dict[str, Any] | None = None,
            api_key: str | None = None,
            timeout: float = 30.0,
            extra_headers: dict[str, str] | None = None,
        ) -> tuple[int, Any]:
            nonlocal n_eval
            if method == "POST" and url.endswith("/v1/decisions/evaluate"):
                n_eval += 1
                return 200, {
                    "trace_id": f"tr-{n_eval}",
                    "decision": "allow",
                    "score": 10.0,
                    "rule_hits": [],
                }
            if method == "POST" and url.endswith("/v1/webhooks/late-label"):
                return 401, {"detail": "invalid or missing request signature"}
            return 404, {}

        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = synth_loop.run_loop(
                request=fake_request,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
                interval=0.0,
                max_events=2,
                label_every=1,
                tenant="demo",
                dry_run=False,
                sleeper=lambda _s: None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(n_eval, 2)
        joined = (buf.getvalue() + err.getvalue()).lower()
        self.assertTrue("warn" in joined or "fail" in joined or "bind" in joined)

    def test_keyboard_interrupt_exits_clean(self) -> None:
        def boom(*_a: Any, **_k: Any) -> tuple[int, Any]:
            raise KeyboardInterrupt

        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = synth_loop.run_loop(
                request=boom,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
                interval=0.0,
                max_events=5,
                label_every=10,
                tenant="demo",
                dry_run=False,
                sleeper=lambda _s: None,
            )
        self.assertEqual(code, 0)


class TestDocsAndMake(unittest.TestCase):
    def test_clone_demo_has_operator_section_after_pass(self) -> None:
        text = (_REPO / "docs/docs/guides/clone-demo.md").read_text(encoding="utf-8")
        pass_at = text.lower().find("after it prints pass")
        self.assertGreaterEqual(pass_at, 0)
        rest = text[pass_at:]
        self.assertIn("synth_loop.py", rest)
        self.assertIn("local operator", rest.lower())
        self.assertNotIn("product SKU", rest)
        self.assertNotIn("open source", rest.lower())

    def test_makefile_has_optional_synth_loop(self) -> None:
        text = (_REPO / "Makefile").read_text(encoding="utf-8")
        self.assertIn("synth-loop", text)
        self.assertIn("synth_loop.py", text)


if __name__ == "__main__":
    unittest.main()
