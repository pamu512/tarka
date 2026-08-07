# Engineering ≥4.7 Implementation Plan

> **Status:** Implemented 2026-08-05 (local gates green; ops-qa-desk PR-gated, first Actions green pending Docker/CI)  
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Earn critical Engineering lens ≥4.7 via surgical honesty stack (mock isolation, PR QA e2e, typed v1 desk surface, expanded audits, contract tests, regrade after green).

**Architecture:** Harden existing gates (`deskMockPolicy`, `audit_prod_desk_mocks.py`, `ops-qa-desk.spec.ts`, case/decision pytest jobs). Do not delete brochure `mockData*`. Demo builds (`VITE_LEAN_NAV=false`) keep mocks; lean/prod desk paths stay mock-free and import `api/v1/*`.

**Tech Stack:** Python 3.12 audits + pytest, GitHub Actions, Playwright, Vite/React frontend, FastAPI case-api/decision-api.

**Spec:** `docs/superpowers/specs/2026-08-05-engineering-4-7-design.md`

## Global Constraints

- Critical bar: do **not** bump Engineering on canvas/matrix until Tasks 1–5 are green.
- Do **not** delete all `mockData*.ts`; isolate from lean desk only.
- Do **not** inflate Risk/Strategy, Fraud Ops, or overall to 4.2.
- Prefer expanding `audit_prod_desk_mocks.py` over a second audit script.
- Prefer `workflow_call` / shared job definition for QA e2e over duplicating steps.
- Commits only when user asks (local agent may stage logical units without pushing).

## File map

| File | Role |
| ---- | ---- |
| `scripts/audit_prod_desk_mocks.py` | Expand: lean desk page + v1 import forbid; lean nav path forbid list |
| `infra/scripts/ci/test_audit_prod_desk_mocks.py` | Self-test: synthetic bad import fails audit helpers |
| `frontend/src/api/v1/decisions.ts` | Re-export full `decisions` (already includes join/dispatch via barrel) |
| `frontend/src/pages/Cases.tsx` | Import cases from `api/v1/cases` |
| `frontend/src/pages/CaseDetail.tsx` | decisions/graph: keep graph from client; cases/decisions from v1 |
| `frontend/src/pages/OpsQaDesk.tsx` | cases from `api/v1/cases` |
| `frontend/src/pages/RulePerformance.tsx` | decisions from `api/v1/decisions` if on lean surface |
| `.github/workflows/ops-qa-desk-e2e.yml` | Add `workflow_call` + `pull_request` |
| `.github/workflows/ci.yml` | Wire audit self-test; optional call QA job or document required check |
| `services/decision-api/tests/test_challenge_dispatch_api.py` | HTTP/unit for POST challenge/dispatch 503/400 |
| `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx` | Engineering ≥4.7 after green |
| `docs/docs/guides/competitive-score-matrix-2026-04.md` | Footnote update after green |

---

### Task 1: Expand prod desk mock audit + lean import forbid

**Files:**
- Modify: `scripts/audit_prod_desk_mocks.py`
- Create: `infra/scripts/ci/test_audit_prod_desk_mocks.py`
- Modify: `.github/workflows/ci.yml` (add self-test step next to existing audit)

**Interfaces:**
- Produces: `LEAN_DESK_PAGES` list, `FORBIDDEN_LEAN_NAV_SUBSTRINGS`, `audit_lean_desk_sources(repo: Path) -> list[str]` used by `main()`

- [ ] **Step 1: Write failing self-test for lean page mockData import**

```python
"""stdlib unittest for audit_prod_desk_mocks lean desk rules."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

# Import helpers after adding them to audit_prod_desk_mocks
from audit_prod_desk_mocks import (  # type: ignore — loaded via path hack in setUp
    scan_lean_desk_violations,
)


class TestLeanDeskAudit(unittest.TestCase):
    def test_flags_mockdata_import_in_lean_page(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page = root / "frontend" / "src" / "pages" / "Cases.tsx"
            page.parent.mkdir(parents=True)
            page.write_text('import { getMockResponse } from "../api/mockData";\n', encoding="utf-8")
            v1 = root / "frontend" / "src" / "api" / "v1" / "cases.ts"
            v1.parent.mkdir(parents=True)
            v1.write_text("export {}\n", encoding="utf-8")
            lean = root / "frontend" / "src" / "config" / "leanNav.ts"
            lean.parent.mkdir(parents=True)
            lean.write_text(
                'export const LEAN_NAV_PATHS = new Set(["/cases"]);\n',
                encoding="utf-8",
            )
            # Minimal client.ts stubs so existing checks can be skipped or stubbed
            client = root / "frontend" / "src" / "api" / "client.ts"
            client.parent.mkdir(parents=True, exist_ok=True)
            client.write_text(
                'const IS_PRODUCTION_BUILD = true;\n'
                'if (IS_PRODUCTION_BUILD && MOCK_MODE === "true") throw new Error("forbidden in production builds");\n'
                "function allowMocksForRequest() {}\n",
                encoding="utf-8",
            )
            policy = root / "frontend" / "src" / "api" / "deskMockPolicy.ts"
            policy.write_text(
                "export function deskStrictEnabled() { return true }\n"
                "export function isDeskApiPath() { return true }\n",
                encoding="utf-8",
            )
            errs = scan_lean_desk_violations(root)
            self.assertTrue(any("mockData" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
```

Note: implementer may path-insert `scripts/` so `import audit_prod_desk_mocks` works (mirror `infra/scripts/ci/test_audit_stubs.py`).

- [ ] **Step 2: Run self-test — expect fail (helper missing)**

```bash
cd /Users/pamu/Documents/GitHub/tarka
PYTHONPATH=scripts python3 infra/scripts/ci/test_audit_prod_desk_mocks.py
```

Expected: ImportError or FAIL until helpers exist.

- [ ] **Step 3: Implement `scan_lean_desk_violations` + wire `main()`**

In `scripts/audit_prod_desk_mocks.py` add:

```python
LEAN_DESK_PAGE_FILES = [
    "frontend/src/pages/Cases.tsx",
    "frontend/src/pages/CaseDetail.tsx",
    "frontend/src/pages/OpsQaDesk.tsx",
    "frontend/src/pages/OpsCalibration.tsx",
    "frontend/src/pages/Disputes.tsx",
    "frontend/src/pages/OpsCounters.tsx",
    "frontend/src/pages/OpsSarTransportBoard.tsx",
    "frontend/src/pages/RulePerformance.tsx",
]

_MOCK_IMPORT_RE = re.compile(r"""from\s+["'][^"']*mockData[^"']*["']|import\s*\([^)]*mockData""")


def scan_lean_desk_violations(repo: Path) -> list[str]:
    errors: list[str] = []
    for rel in LEAN_DESK_PAGE_FILES:
        path = repo / rel
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        if _MOCK_IMPORT_RE.search(src):
            errors.append(f"{rel} imports mockData (forbidden on lean desk)")
    v1_dir = repo / "frontend" / "src" / "api" / "v1"
    if v1_dir.is_dir():
        for path in v1_dir.glob("*.ts"):
            src = path.read_text(encoding="utf-8")
            if _MOCK_IMPORT_RE.search(src):
                errors.append(f"{path.relative_to(repo)} imports mockData")
    lean = repo / "frontend" / "src" / "config" / "leanNav.ts"
    if lean.is_file():
        text = lean.read_text(encoding="utf-8")
        for bad in ("/simulation", "/shadow", "/investigation", "/admin", "/command-center"):
            # Forbid these as members of LEAN_NAV_PATHS set literals
            if re.search(rf'["\']{re.escape(bad)}["\']', text) and "LEAN_NAV_PATHS" in text:
                # Only flag if appears inside the Set initializer block — simple: path string present
                # Narrow: require path listed near LEAN_NAV_PATHS assignment
                block = text.split("LEAN_NAV_PATHS", 1)[-1].split(";", 1)[0]
                if f'"{bad}"' in block or f"'{bad}'" in block:
                    errors.append(f"leanNav.ts LEAN_NAV_PATHS must not include {bad}")
    return errors
```

Call `errors.extend(scan_lean_desk_violations(_REPO))` before the final fail/ok print. Keep existing client.ts checks.

- [ ] **Step 4: Run audit + self-test — expect pass**

```bash
python3 scripts/audit_prod_desk_mocks.py
PYTHONPATH=scripts python3 infra/scripts/ci/test_audit_prod_desk_mocks.py
```

Expected: `audit_prod_desk_mocks: OK` and unittest OK.

- [ ] **Step 5: Add CI step in honesty job**

In `.github/workflows/ci.yml` after `Wave 5 — prod desk mock forbid gate`:

```yaml
      - name: Engineering 4.7 — audit_prod_desk_mocks self-test
        run: PYTHONPATH=scripts python3 infra/scripts/ci/test_audit_prod_desk_mocks.py
```

---

### Task 2: Typed desk API surface (lean pages → api/v1)

**Files:**
- Modify: `frontend/src/pages/Cases.tsx`
- Modify: `frontend/src/pages/OpsQaDesk.tsx`
- Modify: `frontend/src/pages/CaseDetail.tsx` (cases already v1; ensure `decisions` from `api/v1/decisions`)
- Modify: `frontend/src/pages/RulePerformance.tsx` (decisions from v1)
- Modify: `frontend/src/api/v1/decisions.ts` only if join/dispatch need explicit re-export (barrel already exports `decisions`)

**Interfaces:**
- Consumes: `export { decisions, cases, ... } from "../client"` in v1 modules
- Produces: lean pages import cases/decisions/disputes only from `api/v1/*`

- [ ] **Step 1: Write failing vitest for import convention (optional lightweight)**

Prefer relying on Task 1 audit. Skip new vitest if audit covers pages.

- [ ] **Step 2: Migrate Cases.tsx**

Replace:

```ts
import { cases, type Case, type CaseCreateRequest, type CaseDeskActivity, type CaseOpsKpis, toUserFacingApiError } from "../api/client";
```

With:

```ts
import { cases, type Case, type CaseCreateRequest, type CaseDeskActivity, type CaseOpsKpis, toUserFacingApiError } from "../api/v1/cases";
```

- [ ] **Step 3: Migrate OpsQaDesk.tsx**

```ts
import { cases } from "../api/v1/cases";
```

- [ ] **Step 4: Migrate CaseDetail.tsx decisions import**

```ts
import { graph, type EntityRiskResult, type GraphEdge, type GraphNode, type InferenceContext, type SubgraphResponse } from "../api/client";
import { decisions } from "../api/v1/decisions";
import { cases, disputes, type Case, toUserFacingApiError } from "../api/v1/cases";
```

- [ ] **Step 5: Migrate RulePerformance.tsx decisions**

```ts
import { analytics, type AuditEntry } from "../api/client";
import { decisions } from "../api/v1/decisions";
```

(Keep `analytics` on client until a v1 exists — YAGNI.)

- [ ] **Step 6: Verify audit still OK**

```bash
python3 scripts/audit_prod_desk_mocks.py
cd frontend && npx vitest run src/config/leanNav.test.ts
```

Expected: OK / 3 passed.

---

### Task 3: Decision-api challenge dispatch contract test

**Files:**
- Create: `services/decision-api/tests/test_challenge_dispatch_api.py`
- Verify existing: `services/decision-api/tests/test_label_join_and_kill_criteria.py` (y_label store + proxy default)

**Interfaces:**
- Consumes: `dispatch_challenge_from_desk` / FastAPI route `POST /v1/calibration/challenge/dispatch`
- Produces: tests proving 400 for non-step-up, 503 when webhook unset

- [ ] **Step 1: Write failing tests**

```python
"""POST /v1/calibration/challenge/dispatch contract."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("TARKA_CHALLENGE_WEBHOOK_URL", raising=False)
    # Ensure API key auth works like other decision-api tests — follow existing conftest patterns
    from decision_api.main import app

    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "test-key").split(",") if k.strip()]
    return {"X-API-Key": keys[0]}


def test_challenge_dispatch_rejects_non_step_up(client):
    r = client.post(
        "/v1/calibration/challenge/dispatch",
        json={
            "tenant_id": "demo",
            "trace_id": "t1",
            "entity_id": "e1",
            "decision": "review",
            "recommended_action": "manual_review",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("reason_code") == "NOT_STEP_UP_ACTION"


def test_challenge_dispatch_503_when_webhook_unset(client):
    r = client.post(
        "/v1/calibration/challenge/dispatch",
        json={
            "tenant_id": "demo",
            "trace_id": "t1",
            "entity_id": "e1",
            "decision": "review",
            "recommended_action": "step_up_mfa",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 503
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("reason_code") == "CHALLENGE_WEBHOOK_UNCONFIGURED"
```

Adjust path/auth to match decision-api conftest (read `services/decision-api/tests/conftest.py` if present).

- [ ] **Step 2: Run tests**

```bash
cd services/decision-api && .venv/bin/python -m pytest tests/test_challenge_dispatch_api.py tests/test_label_join_and_kill_criteria.py -q --tb=short
```

Expected: PASS (implement route already exists — fix test wiring if auth/tenant middleware blocks).

- [ ] **Step 3: Confirm case-api MC HTTP still in suite**

```bash
cd services/case-api && API_KEYS=test-key PYTHONPATH=src:../shared:../../packages/shared-core \
  .venv/bin/python -m pytest tests/test_maker_checker_http.py -q --tb=short
```

Expected: PASS. No new eng_contract_smoke.py unless these jobs are missing from `ci.yml` (they are present as `test-case-api` / `test-decision-api`).

---

### Task 4: PR-gate ops QA desk Playwright

**Files:**
- Modify: `.github/workflows/ops-qa-desk-e2e.yml`

**Interfaces:**
- Produces: workflow runs on `pull_request` + `workflow_call` + existing schedule/dispatch

- [ ] **Step 1: Add triggers**

```yaml
on:
  workflow_dispatch:
  workflow_call:
  pull_request:
    paths:
      - "frontend/**"
      - "services/case-api/**"
      - "scripts/e2e/**"
      - ".github/workflows/ops-qa-desk-e2e.yml"
  schedule:
    - cron: "0 6 * * 0"
```

Keep job body identical. Optionally set `if: github.event_name != 'pull_request' || ...` — default: always on matching PR paths.

- [ ] **Step 2: Document required check**

Add comment at top of workflow:

```yaml
# Engineering 4.7: PR-gated mock-free QA desk. Required check name: "Ops QA desk e2e / ops-qa-desk"
```

- [ ] **Step 3: Local smoke if micro stack available (optional)**

```bash
# Only if Docker micro profile can boot in this environment:
E2E_QA_DESK=1 E2E_MANAGE_MICRO=1 npm --prefix frontend exec playwright test e2e/ops-qa-desk.spec.ts --reporter=list
```

If local Docker unavailable, rely on PR CI green as acceptance for flag #6.

---

### Task 5: Honesty narrative in ci.yml + STUB/Honesty touch (minimal)

**Files:**
- Modify: `.github/workflows/ci.yml` (Task 1 self-test already added)
- Modify: `docs/TIER_1_HONESTY_PROGRAM.md` — one bullet that Engineering 4.7 gates exist
- Modify: `docs/STUB_REGISTER.md` only if new stubs appear (should not)

- [ ] **Step 1: Add honesty program bullet**

```markdown
- [x] Engineering 4.7 (2026-08-05): lean desk mock import audit + self-test; PR-gated `ops-qa-desk-e2e`; desk pages on `api/v1/*`; MC/label/challenge contracts in pytest CI
```

- [ ] **Step 2: Run stub audit**

```bash
python3 scripts/audit_stubs.py
```

Expected: exit 0.

---

### Task 6: Regrade canvas + matrix (ONLY after Tasks 1–5 green)

**Files:**
- Modify: `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx`
- Modify: Cursor canvas copy at `~/.cursor/projects/Users-pamu-Documents-GitHub-tarka/canvases/maturity-4-0-regrade.canvas.tsx`
- Modify: `docs/docs/guides/competitive-score-matrix-2026-04.md`

**Interfaces:**
- Produces: Engineering **4.7** (or ~4.7); overall may rise slightly but **not** claim 4.2 product-wide

- [ ] **Step 1: Verify gates green locally**

```bash
python3 scripts/audit_prod_desk_mocks.py
PYTHONPATH=scripts python3 infra/scripts/ci/test_audit_prod_desk_mocks.py
python3 scripts/audit_stubs.py
cd frontend && npx vitest run src/config/leanNav.test.ts
cd ../services/decision-api && .venv/bin/python -m pytest tests/test_challenge_dispatch_api.py tests/test_label_join_and_kill_criteria.py -q
cd ../case-api && API_KEYS=test-key PYTHONPATH=src:../shared:../../packages/shared-core .venv/bin/python -m pytest tests/test_maker_checker_http.py -q
```

- [ ] **Step 2: Update canvas stats**

Set Engineering lens to **4.7**, note evidence: `audit_prod_desk_mocks`, PR `ops-qa-desk-e2e`, v1 desk imports, MC/label/challenge pytest. Keep Location ~2.9; do not set overall to 4.2.

- [ ] **Step 3: Matrix footnote**

Add line under critical correction: Engineering critical **≥4.7** after surgical honesty stack (date + script/job names).

---

## Spec coverage check

| Spec section | Task |
| ------------ | ---- |
| §1 MockData isolation | Task 1 |
| §2 PR QA e2e | Task 4 |
| §3 Honesty gate expansion | Task 1 + 5 |
| §4 Typed desk API | Task 2 |
| §5 Service contracts | Task 3 (+ existing CI jobs) |
| §6 Regrade after green | Task 6 |
| Acceptance checklist | Task 6 Step 1 |

## Placeholder scan

None intentional. Playwright local boot may be skipped if Docker unavailable — PR CI is the acceptance path for flag #6.
