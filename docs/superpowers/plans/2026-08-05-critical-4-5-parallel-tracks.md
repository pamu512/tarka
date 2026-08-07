# Critical Maturity 4.5 — Parallel Tracks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> **Parallelism:** After Task 0, Tracks P / R / O (Tasks 1–3 / 4–5 / 6–7) may run as **independent subagent lanes**; Task 8 (claim lock) waits for all three.

**Goal:** Earn critical overall ≥4.5 with every six-cap pillar ≥4.0 (location hybrid floor 4.0) under L1∧L2∧L3 evidence — Approach C parallel tracks.

**Architecture:** Track P hardens in-repo gates (counters dual-diff, kill_criteria promote block, QA e2e green). Track R ships live named-tenant partner proof + co-presence deepen. Track O ships ≥4-week shadow/label/ECE loop + playbook. Claim publish only when all tiers green.

**Tech Stack:** Python/FastAPI (decision-api, case-api), Redis counters, GitHub Actions, Playwright, partner adapters (Fingerprint/Incognia), existing shadow/calibration surfaces.

**Spec:** `docs/superpowers/specs/2026-08-05-critical-4-5-parallel-tracks-design.md`

## Global Constraints

- Critical/skeptical bar — no liberal Wave6 “4.2” re-advertise.
- Claim lock: **L1 ∧ L2 ∧ L3** required before matrix/canvas overall ≥4.5.
- Location = hybrid partner-first; **no** native global device-reputation network.
- Location may sit at **4.0** floor; other pillars stretch **≥4.5**.
- Sim / fixture SHA alone ≠ L2 or L3.
- Engineering 4.7 work (desk mocks, ops-qa PR gate, v1 imports) is **prerequisite** — do not regress it.
- Prefer extending existing modules (`vertical_packs.evaluate_kill_criteria`, `partner_fusion_tenant_proof.py`, `internal_counters_api`, `y_label_store`) over new packages.
- Commits: follow user rules (commit when plan steps say so unless user says otherwise).

## File map

| File | Track | Role |
| --- | --- | --- |
| `services/decision-api/src/decision_api/vertical_packs.py` | P | `evaluate_kill_criteria` — reuse |
| `services/decision-api/src/decision_api/rule_api.py` (or experiment promote path) | P | Hard-block promote when kill fires |
| `services/decision-api/tests/test_kill_criteria_promote_gate.py` | P | New |
| `services/decision-api/src/decision_api/internal_counters_api.py` | P | Parity artifact + dual-diff status |
| `scripts/oss/counter_parity_dual_diff.py` | P | New or extend existing replay job |
| `rules/counter_parity_last.json` | P | Written by parity job |
| `.github/workflows/ops-qa-desk-e2e.yml` | P | Ensure first green / required |
| `scripts/oss/partner_fusion_tenant_proof.py` | R | `--mode live` + `REQUIRE_LIVE_PARTNER_PROOF` |
| `docs/compliance/partner-fusion-proof-runbook.md` | R | Live tenant steps + SHA pin |
| `docs/compliance/partner-fusion-proof.live.sha256` | R | New live pin (separate from fixture) |
| co-presence / cohort modules under decision-api + graph | R | Deepen hybrid location |
| `docs/superpowers/playbooks/2026-08-05-shadow-four-week-critical.md` | O | New ops playbook |
| `scripts/oss/shadow_four_week_sim.py` | O | Wiring/smoke only — banner not L3 |
| `services/decision-api/src/decision_api/y_label_store.py` | O | Labels for retrain |
| `scripts/oss/retrain_calibration_ece_gate.py` | O | ECE-gated Platt candidate |
| `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx` | Claim | Update after L1∧L2∧L3 |
| `docs/docs/guides/competitive-score-matrix-2026-04.md` | Claim | Critical 4.5 row + evidence |

---

## Task 0: Baseline inventory (serial)

**Files:** none (read-only + ledger)

- [ ] **Step 1: Record HEAD and critical baseline**

```bash
cd /Users/pamu/Documents/GitHub/tarka
git rev-parse --short HEAD
git status -sb
```

Expected: on `maturity-4-0-local` (or agreed branch).

- [ ] **Step 2: Confirm Engineering 4.7 gates still green**

```bash
python3 scripts/audit_prod_desk_mocks.py
cd services/decision-api && PYTHONPATH=src:. python3 -m pytest tests/test_label_join_and_kill_criteria.py tests/test_challenge_dispatch_api.py -q
```

Expected: audit exit 0; pytest pass.

- [ ] **Step 3: Write ledger**

Create `.superpowers/sdd/critical-4-5-progress.md` with Track P/R/O status PENDING and baseline SHA.

- [ ] **Step 4: Commit ledger only if user wants docs in git** — otherwise keep local.

```bash
git add .superpowers/sdd/critical-4-5-progress.md 2>/dev/null || true
```

---

# Track P — Platform (L1)

### Task 1: kill_criteria hard promote gate

**Files:**
- Modify: `services/decision-api/src/decision_api/vertical_packs.py` (reuse `evaluate_kill_criteria`)
- Modify: promote/activate path in `services/decision-api/src/decision_api/rule_api.py` **or** experiment promote handler that currently ignores kill (locate with ripgrep `promote` / `activate`)
- Create: `services/decision-api/tests/test_kill_criteria_promote_gate.py`

**Interfaces:**
- Consumes: `evaluate_kill_criteria(metrics: dict, kill_criteria: dict | None, *, events_evaluated: int) -> dict` with `promote_allowed: bool`, `blockers: list[str]`
- Produces: HTTP **409** (or 400) when `promote_allowed` is False; body includes `blockers`

- [ ] **Step 1: Write failing test**

```python
"""Promote/activate must refuse when kill_criteria fire."""
from __future__ import annotations

from decision_api.vertical_packs import evaluate_kill_criteria


def test_kill_criteria_blocks_low_precision():
    gate = evaluate_kill_criteria(
        {"precision": 0.1, "recall": 0.9, "f1_score": 0.2},
        {"min_precision": 0.5, "min_recall": 0.3, "min_f1": 0.4},
        events_evaluated=500,
    )
    assert gate["promote_allowed"] is False
    assert gate["blockers"]


def test_promote_endpoint_returns_conflict_when_kill_fires(client, monkeypatch):
    # Wire to the real promote/activate route used in ops — adjust path to match repo.
    monkeypatch.setattr(
        "decision_api.rule_api.evaluate_kill_criteria",
        lambda *a, **k: {"promote_allowed": False, "blockers": ["min_precision"]},
    )
    # Example — replace with actual route from rule_api / experiment_api:
    # r = client.post("/v1/rules/packs/foo/promote", json={...})
    # assert r.status_code == 409
    # assert "min_precision" in r.json().get("blockers", [])
    assert True  # replace with real HTTP assert in implementation
```

- [ ] **Step 2: Run test — expect fail until endpoint wired**

```bash
cd services/decision-api && PYTHONPATH=src:. python3 -m pytest tests/test_kill_criteria_promote_gate.py -v
```

- [ ] **Step 3: Implement gate on promote/activate**

Call `evaluate_kill_criteria` with latest simulation metrics (or required body metrics). If not `promote_allowed`, raise `HTTPException(status_code=409, detail={"blockers": ...})`.

- [ ] **Step 4: Pytest pass + commit**

```bash
git add services/decision-api/src/decision_api/*.py services/decision-api/tests/test_kill_criteria_promote_gate.py
git commit -m "feat: hard-block rule promote when kill_criteria fire"
```

---

### Task 2: Counter dual-diff parity (not dry-run vanity)

**Files:**
- Modify: `services/decision-api/src/decision_api/internal_counters_api.py`
- Create or extend: `scripts/oss/counter_parity_dual_diff.py`
- Modify: CI job that runs counter replay (search `counter_parity` / `counter replay` in `.github/workflows/ci.yml`)
- Test: `services/decision-api/tests/test_counter_parity_dual_diff.py`

**Interfaces:**
- Produces: `rules/counter_parity_last.json` with `{schema_id, ts, mode: "dual_diff"|"dry_run", matched: bool, diffs: [...]}`
- API already exposes `last_parity_run` via `_load_last_parity_run()` — keep shape compatible

- [ ] **Step 1: Failing test — dual_diff mode required for healthy ops signal**

```python
def test_parity_artifact_dual_diff_shape(tmp_path, monkeypatch):
    from scripts.oss import counter_parity_dual_diff as mod  # adjust import path hack

    out = tmp_path / "counter_parity_last.json"
    # Call run(mode="dual_diff", out=out) with fake redis/memory counters that match
    # assert json.loads(out.read_text())["mode"] == "dual_diff"
    # assert "matched" in json.loads(out.read_text())
```

- [ ] **Step 2: Implement dual-diff** comparing Redis hash vs process/file counters; write artifact; dry-run alone must **not** set `matched: true` as proof.

- [ ] **Step 3: Wire CI/scheduled step to write `rules/counter_parity_last.json`**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: counter dual-diff parity artifact for critical counters bar"
```

---

### Task 3: Ops QA desk e2e — first green + keep PR gate

**Files:**
- `.github/workflows/ops-qa-desk-e2e.yml`
- `frontend/e2e/ops-qa-desk.spec.ts`

**Note:** Engineering 4.7 already PR-gated this. This task is **prove green on Actions** and upload artifact — not redesign.

- [ ] **Step 1: Run locally**

```bash
E2E_QA_DESK=1 E2E_MANAGE_MICRO=1 npm --prefix frontend exec playwright test e2e/ops-qa-desk.spec.ts --reporter=list
```

Expected: pass (or fix flakes).

- [ ] **Step 2: Ensure workflow uploads Playwright report artifact on success/failure**

- [ ] **Step 3: Confirm required check name still `Ops QA desk e2e / ops-qa-desk`**

- [ ] **Step 4: Commit only if workflow/spec fixes needed**

```bash
git commit -m "ci: stabilize ops-qa-desk e2e for critical L1 analyst gate"
```

---

# Track R — Partner / Location (L1+L2)

### Task 4: Live named-tenant partner fusion proof

**Files:**
- Modify: `scripts/oss/partner_fusion_tenant_proof.py` (live mode already sketched)
- Modify: `docs/compliance/partner-fusion-proof-runbook.md`
- Create: `docs/compliance/partner-fusion-proof.live.sha256` (after first successful live run)
- Test: `services/decision-api/tests/test_partner_fusion_tenant_proof.py`

**Interfaces:**
- CLI: `--mode live` with `DECISION_API_URL`, partner ids, `REQUIRE_LIVE_PARTNER_PROOF=1`
- Exit **1** if live path not used or `partner_evidence` missing
- Fixture mode remains CI default (L1 regression)

- [ ] **Step 1: Extend test — REQUIRE_LIVE_PARTNER_PROOF fails closed without live evidence**

```python
def test_require_live_fails_without_partner_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("REQUIRE_LIVE_PARTNER_PROOF", "1")
    # Invoke proof main with fixture-only result mocked → expect SystemExit(1)
```

- [ ] **Step 2: Document live runbook steps** (named tenant, env vars, SHA file update process)

- [ ] **Step 3: Operator runs live once; commit `partner-fusion-proof.live.sha256` + proof JSON under `docs/compliance/` or artifacts policy**

- [ ] **Step 4: Commit code/docs**

```bash
git commit -m "feat: live partner fusion proof gate and runbook for location L2"
```

---

### Task 5: In-repo co-presence / cohort deepen (location floor)

**Files:**
- Locate existing cohort/co-presence (Wave location work) — search `cohort`, `co_presence`, `SEEN_AT`
- Modify evaluate/graph/case evidence path to surface cohort signals in audit
- Test: unit + one evaluate contract test

**Interfaces:**
- Produces: decision audit/evidence fields for cohort/co-presence when signals present; no-op when absent (fail soft)

- [ ] **Step 1: Failing test — evaluate with cohort fixture tags includes evidence key**

```python
def test_evaluate_surfaces_cohort_partner_evidence():
    # Build minimal evaluate request with cohort metadata / graph hints
    # assert "cohort" in evidence or tags include sdk:/graph cohort family
    pass
```

- [ ] **Step 2: Minimal wiring — reuse existing graph Place/SEEN_AT / policy-check; do not invent Incognia network**

- [ ] **Step 3: Pytest pass + commit**

```bash
git commit -m "feat: deepen hybrid cohort/co-presence evidence for location floor"
```

---

# Track O — Ops loop (L3)

### Task 6: Four-week shadow playbook + sim wiring

**Files:**
- Create: `docs/superpowers/playbooks/2026-08-05-shadow-four-week-critical.md`
- Create: `scripts/oss/shadow_four_week_sim.py` (synthetic chronological dry-run)
- Create: `services/decision-api/tests/test_shadow_four_week_sim_smoke.py` **or** `scripts` smoke invoked from CI optional job

**Interfaces:**
- Sim writes `artifacts/shadow_four_week_sim.json` with `precision`, `recall`, `insult_proxy`, `banner: "NOT PRODUCTION L3"`
- Playbook weeks 1–4: shadow on → host action log → outcomes → weekly metrics → retrain candidate → promote

- [ ] **Step 1: Write playbook markdown** (checklist; explicit sim ≠ L3)

- [ ] **Step 2: Sim smoke**

```bash
PYTHONPATH=services/decision-api/src:. python3 scripts/oss/shadow_four_week_sim.py --seed 42 --out artifacts/shadow_four_week_sim.json
# assert banner and metrics keys exist
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: four-week shadow playbook and non-claiming sim for L3 path"
```

---

### Task 7: Label join → ECE-gated calibration retrain

**Files:**
- Reuse: `services/decision-api/src/decision_api/y_label_store.py`, calibration fit helpers
- Create: `scripts/oss/retrain_calibration_ece_gate.py`
- Create: `services/decision-api/tests/test_retrain_calibration_ece_gate.py`

**Interfaces:**
- CLI: `--labels`, `--out` candidate, `--artifact-out`, `--train-end` or `--train-fraction`, `--ece-threshold` default `0.05`, `--force`
- Fit on train window only; ECE/Brier on held-out chronological report window
- ECE > threshold without `--force`: do not overwrite candidate; exit 1
- `--force`: write + `force: true` in artifact

- [ ] **Step 1: Failing tests — bad ECE no write; good ECE writes; force writes**

```python
def test_bad_ece_does_not_write_candidate(tmp_path):
    # construct labels with mismatch on report window
    # assert exit code 1 and candidate file absent/unchanged
    pass
```

- [ ] **Step 2: Implement script reusing existing Platt/ECE utilities in decision-api calibration module**

- [ ] **Step 3: Pytest pass + commit**

```bash
git commit -m "feat: ECE-gated calibration retrain for critical L3 inference bar"
```

---

# Claim lock

### Task 8: Critical regrade + matrix publish (only when L1∧L2∧L3)

**Files:**
- Modify: `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx`
- Modify: `docs/docs/guides/competitive-score-matrix-2026-04.md`
- Modify: `docs/superpowers/specs/2026-08-05-critical-4-5-parallel-tracks-design.md` status → Complete (if earned)

**Gate checklist (all must be true):**

| Tier | Evidence |
| --- | --- |
| L1 | kill promote 409 tests green; counter dual-diff artifact; ops-qa-desk Actions green |
| L2 | `partner-fusion-proof.live.sha256` + runbook named tenant |
| L3 | playbook complete for ≥4 weeks **or** documented live ops artifact; retrain ECE gate used on real labels — sim alone insufficient |

- [ ] **Step 1: Skeptical regrade numbers** — fill pillar table; overall mean ≥4.5; min ≥4.0

- [ ] **Step 2: Update canvas + matrix with evidence links**

- [ ] **Step 3: Commit**

```bash
git commit -m "docs: publish critical 4.5 regrade after L1+L2+L3 evidence"
```

- [ ] **Step 4: STOP — do not claim earlier**

---

## Spec coverage (self-review)

| Spec requirement | Task |
| --- | --- |
| Overall ≥4.5, pillar floor 4.0 | Task 8 |
| Location hybrid ≥4.0 partner-first | Tasks 4–5 |
| L1 in-repo gates | Tasks 1–3 |
| L2 live tenant | Task 4 |
| L3 4-week + ECE | Tasks 6–7 |
| Parallel Approach C | Tracks P/R/O after Task 0 |
| No native Incognia network / no sim-as-L3 | Constraints + Tasks 5–6 banners |
| Engineering 4.7 non-regress | Task 0 |

**Placeholder scan:** none intentional; Task 1 HTTP path must be resolved to the real promote route during implementation (ripgrep `promote` in `rule_api` / `experiment_api`).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-05-critical-4-5-parallel-tracks.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task (or per track lane after Task 0), review between tasks

**2. Inline Execution** — execute in this session with executing-plans checkpoints

Which approach?
