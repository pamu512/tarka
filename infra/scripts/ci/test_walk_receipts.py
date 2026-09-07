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

import first_decision_smoke  # noqa: E402
import walk_receipts  # noqa: E402


class TestFirstDecisionSmoke(unittest.TestCase):
    def test_main_prints_ok_audit_when_tenant_query_present(self) -> None:
        seen: list[str] = []

        def fake_request(
            method: str,
            url: str,
            *,
            payload: dict[str, Any] | None = None,
            api_key: str | None = None,
            timeout: float = 30.0,
        ) -> tuple[int, Any]:
            seen.append(url)
            if method == "GET" and url.endswith("/v1/health"):
                return 200, {"status": "ok"}
            if method == "POST":
                return 200, {"trace_id": "t-1", "decision": "allow", "score": 1.0}
            if method == "GET" and "/v1/audit/" in url:
                if "tenant_id=demo" not in url:
                    return 422, {"detail": "tenant_id Field required"}
                return 200, {"trace_id": "t-1", "tenant_id": "demo"}
            return 404, {}

        buf = io.StringIO()
        orig = first_decision_smoke._request
        first_decision_smoke._request = fake_request  # type: ignore[method-assign]
        try:
            with redirect_stdout(buf):
                code = first_decision_smoke.main()
        finally:
            first_decision_smoke._request = orig  # type: ignore[method-assign]
        self.assertEqual(code, 0)
        self.assertTrue(any("/v1/audit/" in u and "tenant_id=demo" in u for u in seen))
        self.assertIn("[ok] audit fetch", buf.getvalue())
        self.assertNotIn("[warn] audit GET", buf.getvalue())


class TestAuditTenantQuery(unittest.TestCase):
    def test_audit_url_requires_tenant_query(self) -> None:
        url = first_decision_smoke.audit_url(
            "http://127.0.0.1:8000/decisions",
            "trace-1",
            "demo",
        )
        self.assertEqual(
            url,
            "http://127.0.0.1:8000/decisions/v1/audit/trace-1?tenant_id=demo",
        )
        self.assertIn("tenant_id=", url)


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
        self.assertIn("sibling", joined)
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


class TestTipClaimsHonesty(unittest.TestCase):
    """Buyer-facing tip claims stay true. Path names under scripts/oss/ may stay."""

    _BUYER = (
        "README.md",
        "VISION.md",
        "CONTRIBUTING.md",
        "docs/INDEX.md",
        "docs/docs/index.md",
        "docs/docs/quickstart.md",
        "docs/docs/guides/clone-demo.md",
        "docs/docs/guides/product-day1-install.md",
        "docs/docs/guides/hop-pack-authoring.md",
        "docs/docs/guides/gnn-label-loop.md",
        "docs/docs/guides/graph-analysis.md",
        "docs/docs/guides/feature-data-flows.md",
        "docs/docs/guides/oss-15-minute-first-decision.md",
        "docs/docs/guides/shadow-and-ab-testing.md",
        "frontend/src/pages/PlaneOff.tsx",
        "frontend/src/pages/Settings.tsx",
        "frontend/src/pages/Help.tsx",
        "frontend/src/components/AnalystReadinessBar.tsx",
        "infra/deploy/docker-compose.lite.yml",
    )
    _HOP_PACKS = (
        "services/decision-api/rules/graph_v1_uses_device_v1.json",
        "services/decision-api/rules/graph_v1_has_instrument_v1.json",
        "services/decision-api/rules/graph_v1_has_list_v1.json",
        "services/decision-api/rules/graph_shared_device_v1.json",
        "services/decision-api/rules/location_copresence_v1.json",
        "services/decision-api/rules/seed_promo_observe_v1.json",
        "services/decision-api/rules/seed_cod_observe_v1.json",
        "services/decision-api/rules/seed_payout_observe_v1.json",
    )
    _BANNED = (
        "flip mode to active",
        "this oss console",
        "oss 15-minute path",
        "written for **beta testers**",
        "then auto-promotes",
        "that is an outage",
        "is an outage.",
        "/cases/v1/cases",
    )

    def test_buyer_copy_has_no_shipped_overclaims(self) -> None:
        for rel in self._BUYER:
            text = (_REPO / rel).read_text(encoding="utf-8").lower()
            for phrase in self._BANNED:
                self.assertNotIn(phrase, text, rel)

    def test_readme_names_elv2_beta_and_doctor(self) -> None:
        text = (_REPO / "README.md").read_text(encoding="utf-8").lower()
        self.assertIn("elastic license 2.0", text)
        self.assertIn("not open-source", text)
        self.assertIn("beta", text)
        self.assertIn("make doctor && make demo", text)
        self.assertIn("not sibling identity", text)

    def test_hop_packs_stay_shadow(self) -> None:
        import json

        for rel in self._HOP_PACKS:
            pack = json.loads((_REPO / rel).read_text(encoding="utf-8"))
            self.assertEqual(pack.get("mode"), "shadow", rel)
            self.assertNotIn("flip mode to active", json.dumps(pack).lower())

    def test_compose_does_not_enable_gnn_beta_url(self) -> None:
        for path in (_REPO / "infra" / "deploy").rglob("docker-compose*.yml"):
            blob = path.read_text(encoding="utf-8")
            self.assertNotIn("GRAPH_GNN_BETA_URL", blob, str(path))


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

    def test_run_walk_audit_passes_tenant_id_and_prints_ok(self) -> None:
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
        seen_audit: list[str] = []

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
            if method == "GET" and "/v1/audit/" in url:
                seen_audit.append(url)
                if "tenant_id=demo" in url:
                    return 200, {"trace_id": "t", "tenant_id": "demo"}
                return 422, {"detail": [{"loc": ["query", "tenant_id"], "msg": "Field required"}]}
            return 404, {}

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = walk_receipts.run_walk(
                request=fake_request,
                base="http://127.0.0.1:8000/decisions",
                api_key=None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(seen_audit), 3)
        for url in seen_audit:
            self.assertIn("tenant_id=demo", url)
        self.assertIn("[ok] audit fetch", buf.getvalue())
        self.assertNotIn("[warn] audit GET", buf.getvalue())

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
