#!/usr/bin/env python3
"""Offline tests for the optional Python SDK receipt walk (stdlib).

Mirrors test_walk_receipts: mocked client, no live HTTP, no invented
expected_decision on cases. Run:

  PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_sdk_walk.py
"""

from __future__ import annotations

import ast
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
_OSS = _REPO / "scripts" / "oss"
if str(_OSS) not in sys.path:
    sys.path.insert(0, str(_OSS))

import sdk_walk  # noqa: E402
import walk_receipts  # noqa: E402

_CANNED = {
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


class _FakeClient:
    def __init__(self, canned: dict[str, dict[str, Any]]) -> None:
        self.canned = canned
        self.evaluate_calls: list[dict[str, Any]] = []
        self.audit_calls: list[tuple[str, str]] = []

    def evaluate(
        self,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        device_context: dict[str, Any] | None = None,
        role: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.evaluate_calls.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "entity_id": entity_id,
                "payload": payload,
                "device_context": device_context,
                "role": role,
            }
        )
        if entity_id not in self.canned:
            raise KeyError(entity_id)
        return self.canned[entity_id]

    def get_audit(self, trace_id: Any, tenant_id: str) -> dict[str, Any]:
        self.audit_calls.append((str(trace_id), tenant_id))
        return {"trace_id": str(trace_id), "tenant_id": tenant_id}


def _ok_health(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    if method == "GET" and url.endswith("/v1/health"):
        return 200, {"status": "ok"}
    return 404, {}


class TestSdkWalkCases(unittest.TestCase):
    def test_reuses_same_three_shipped_pack_cases(self) -> None:
        self.assertIs(sdk_walk.WALK_CASES, walk_receipts.WALK_CASES)
        self.assertGreaterEqual(len(sdk_walk.WALK_CASES), 3)
        for case in sdk_walk.WALK_CASES:
            self.assertNotIn("expected_decision", case)
            self.assertNotIn("decision", case)


class TestSdkWalkHonesty(unittest.TestCase):
    def test_honesty_reuses_walk_lines_and_names_elv2(self) -> None:
        lines = sdk_walk.honesty_lines()
        walk_lines = walk_receipts.looking_at_lines()
        self.assertEqual(lines[: len(walk_lines)], walk_lines)
        joined = "\n".join(lines).lower()
        self.assertIn("graph_service_url", joined)
        self.assertIn("observe", joined)
        self.assertTrue("hop" in joined or "edge" in joined)
        self.assertTrue("elastic license" in joined or "elv2" in joined)
        self.assertTrue("not open-source" in joined or "not oss" in joined)
        self.assertNotIn("hop warmer", joined)
        self.assertNotIn("marketplace", joined)
        self.assertNotIn("seed→live", joined)
        self.assertNotIn("seed->live", joined)
        self.assertNotIn("automl", joined)
        self.assertNotIn("auto-promote", joined)

    def test_script_source_has_no_theater(self) -> None:
        src = (_REPO / "scripts" / "oss" / "sdk_walk.py").read_text(encoding="utf-8").lower()
        for banned in (
            "hop warmer",
            "curated marketplace",
            "seed→live",
            "seed->live",
            "expected_decision",
            "automl",
        ):
            self.assertNotIn(banned, src)

    def test_script_does_not_assert_allow_deny(self) -> None:
        tree = ast.parse((_REPO / "scripts" / "oss" / "sdk_walk.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                literals = []
                for child in [node.left, *node.comparators]:
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        literals.append(child.value.lower())
                if any(word in literals for word in ("allow", "review", "deny")):
                    self.fail(f"sdk_walk compares against a decision literal: {literals}")


class TestSdkWalkRunner(unittest.TestCase):
    def test_run_walk_prints_engine_decision_why_entity(self) -> None:
        client = _FakeClient(_CANNED)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = sdk_walk.run_walk(
                request=_ok_health,
                client=client,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(client.evaluate_calls), 3)
        entities = [c["entity_id"] for c in client.evaluate_calls]
        self.assertEqual(
            entities,
            [c["body"]["entity_id"] for c in walk_receipts.WALK_CASES],
        )
        bot = next(c for c in client.evaluate_calls if c["entity_id"] == "clone-demo-bot")
        self.assertEqual(bot["device_context"]["signals"]["is_bot"], True)
        for call, case in zip(client.evaluate_calls, walk_receipts.WALK_CASES, strict=True):
            self.assertEqual(call["role"], case["body"]["role"])
            self.assertEqual(call["role"], "member")
        out = buf.getvalue()
        self.assertIn("allow", out.lower())
        self.assertIn("review", out.lower())
        self.assertIn("deny", out.lower())
        self.assertIn("clone-demo-clean", out)
        self.assertIn("sdk_bot", out)
        self.assertIn("http://127.0.0.1:3000", out)
        self.assertIn("NEXT: http://127.0.0.1:3000/graph?entity_id=clone-demo-bot-vpn", out)
        self.assertNotIn("ALLOW $42", out)
        self.assertNotIn("hop warmer", out.lower())
        self.assertEqual(len(client.audit_calls), 3)
        for _trace, tenant in client.audit_calls:
            self.assertEqual(tenant, "demo")
        self.assertIn("[ok] audit fetch", out)

    def test_run_walk_audit_warn_does_not_fail(self) -> None:
        class _NoAudit(_FakeClient):
            def get_audit(self, trace_id: Any, tenant_id: str) -> dict[str, Any]:
                raise RuntimeError("audit down")

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = sdk_walk.run_walk(
                request=_ok_health,
                client=_NoAudit(_CANNED),
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 0)
        self.assertIn("[warn] audit GET", buf.getvalue())

    def test_run_walk_fails_closed_on_bad_health(self) -> None:
        def dead_request(method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
            return 0, "connection refused"

        client = _FakeClient(_CANNED)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = sdk_walk.run_walk(
                request=dead_request,
                client=client,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 1)
        self.assertEqual(client.evaluate_calls, [])

    def test_run_walk_fails_closed_on_evaluate_error(self) -> None:
        class _Boom(_FakeClient):
            def evaluate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("401 unauthorized")

        err = io.StringIO()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = sdk_walk.run_walk(
                request=_ok_health,
                client=_Boom(_CANNED),
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 1)
        self.assertIn("[fail] evaluate", err.getvalue())

    def test_run_walk_prints_auth_hint_on_401(self) -> None:
        class _Auth(_FakeClient):
            def evaluate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                exc = RuntimeError("unauthorized")
                exc.response = type("R", (), {"status_code": 401})()
                raise exc

        err = io.StringIO()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = sdk_walk.run_walk(
                request=_ok_health,
                client=_Auth(_CANNED),
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 1)
        self.assertIn("ALLOW_INSECURE_NO_AUTH", err.getvalue())


if __name__ == "__main__":
    unittest.main()
