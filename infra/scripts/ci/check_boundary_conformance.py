#!/usr/bin/env python3
"""Evaluate-plane boundary conformance as code (C/M guardrails, G14).

Mechanizes the mechanically-checkable subset of the guardrail boundary tests
in the strategy pack (04-evaluate-plane-guardrails):

  M2  no assignee/SLA/ticket-routing fields on case/leftover record models
  C5  analytics endpoints do not aggregate across tenants by default
      (tenant_id is a required query param, not optional-with-all-tenants)
  M6  lean nav does not surface fat /cases
  C2  CLAIM_LOCK: repo docs do not sell a "Consortium SKU"

This is grep/AST-level by design: fast, zero deps, runs in CI. It is a
tripwire, not a proof — behavioral enforcement lives in the suites. Exits
non-zero with one line per violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FAILURES: list[str] = []


def fail(check: str, detail: str) -> None:
    FAILURES.append(f"[{check}] {detail}")


# --- M2: queue semantics must not appear on record models -------------------

M2_MODEL_FILES = [
    ROOT / "services" / "case-api" / "src" / "case_api" / "models.py",
]
M2_FORBIDDEN = re.compile(
    r"^\s*(assignee|assigned_to|sla_|due_at|ticket_id|queue_position)\s*[:=]",
    re.MULTILINE,
)


def check_m2() -> None:
    for path in M2_MODEL_FILES:
        if not path.is_file():
            fail("M2", f"model file missing: {path.relative_to(ROOT)}")
            continue
        hits = M2_FORBIDDEN.findall(path.read_text(encoding="utf-8"))
        # findall returns groups; re-scan line-wise for reporting
        for line in path.read_text(encoding="utf-8").splitlines():
            if M2_FORBIDDEN.match(line):
                fail("M2", f"queue-semantics field in {path.name}: {line.strip()[:80]}")


# --- C5: analytics endpoints require tenant scoping --------------------------

C5_SCAN_DIRS = [
    ROOT / "services" / "graph-service" / "src" / "graph_service",
    ROOT / "services" / "decision-api" / "src" / "decision_api",
]
C5_ROUTE = re.compile(
    r'@app\.(get|post)\("/v1/analytics/[^"]*"(.*?)\)\s*\nasync def (\w+)\(([^)]*)\)',
    re.MULTILINE | re.DOTALL,
)

# Endpoints exempt from tenant scoping: process-level ops counters that
# contain no entity/decision data. usage_snapshot() returns per-surface and
# per-tenant invocation counts only (explainability_usage.py).
C5_EXEMPT = {"explainability_usage_endpoint"}


def check_c5() -> None:
    for base in C5_SCAN_DIRS:
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for m in C5_ROUTE.finditer(text):
                params = m.group(4)
                fn = m.group(3)
                if fn in C5_EXEMPT:
                    continue
                # tenant scoping may arrive as a query param OR via a request
                # body model (body.tenant_id) — either satisfies C5.
                if "tenant_id" not in params and "body" not in params:
                    rel = path.relative_to(ROOT)
                    fail(
                        "C5",
                        f"{rel}:{fn} analytics endpoint without tenant scoping",
                    )


# --- M6: lean nav keeps /cases out of the nav --------------------------------

LEAN_NAV = ROOT / "frontend" / "src" / "config" / "leanNav.ts"


def check_m6() -> None:
    if not LEAN_NAV.is_file():
        fail("M6", "leanNav.ts missing")
        return
    text = LEAN_NAV.read_text(encoding="utf-8")
    # The invariant: /cases nav item is hidden in demo/product profiles.
    # Enforced in isNavItemVisible; /cases may appear in LEAN_NAV_PATHS only as
    # a residual deep-link (guardrail doc: "reachable as residual deep-link").
    if not re.search(
        r'path\s*===\s*"/cases"\s*\)\s*return\s+false', text
    ):
        fail("M6", 'isNavItemVisible no longer hides "/cases" in demo/product profiles')


# --- C2: no affirmative Consortium SKU marketing in repo docs ----------------
#
# Mentions inside must-not/out-of-scope lists are the CLAIM_LOCK working
# correctly (e.g. "| Consortium SKU |" rows in must-not tables, "- Consortium
# SKU" bullets in out-of-scope lists). Only affirmative selling language is a
# violation.

C2_SCAN = ROOT / "docs"
C2_FORBIDDEN = re.compile(
    r"[^.]\b(?:buy|purchase|sell|subscribe|pricing|price|tier|plan)\b[^.]*\bconsortium\s+SKU\b"
    r"|\bconsortium\s+SKU\b[^.]*\b(?:available|included|for sale|purchase)\b",
    re.IGNORECASE,
)


def check_c2() -> None:
    for path in sorted(C2_SCAN.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for m in C2_FORBIDDEN.finditer(text):
            rel = path.relative_to(ROOT)
            snippet = text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
            fail("C2", f"affirmative Consortium-SKU language in {rel}: ...{snippet}...")


def main() -> int:
    check_m2()
    check_c5()
    check_m6()
    check_c2()
    if FAILURES:
        print("boundary conformance: FAIL")
        for line in FAILURES:
            print(f"  {line}")
        return 1
    print("boundary conformance: OK (M2, C5, M6, C2 checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
