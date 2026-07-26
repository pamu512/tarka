# Fraud spine Phase 1 remainder — Implementation Plan

> **For agentic workers:** Implement task-by-task; verify each task before the next.

**Goal:** Land production fail-closed profile, degraded SLO surface, and evaluate package split on `chore/fraud-spine-phase-0-1`.

**Architecture:** Extend existing governance/SLO surfaces; move evaluate helpers into `decision_api/evaluate/` without changing evaluate semantics.

**Tech stack:** Python 3.12, FastAPI decision-api, pytest, Grafana JSON provisioning, GitHub Actions.

---

### Task 1: Production profile module + tests

**Files:**
- Create: `services/decision-api/src/decision_api/production_profile.py`
- Create: `services/decision-api/tests/test_production_profile.py`
- Create: `infra/deploy/release/fixtures/production-profile.ok.env`
- Create: `infra/deploy/release/fixtures/production-profile.bad.env`
- Create: `scripts/release/assert_production_profile.py`
- Modify: `services/decision-api/src/decision_api/config.py`, `main.py` lifespan
- Modify: `infra/deploy/release/governance-checklist.yaml`, `.github/workflows/ci.yml`

### Task 2: Degraded SLO API + Grafana

**Files:**
- Modify: `services/shared/observability.py`
- Modify: `services/decision-api/src/decision_api/main.py` (`/v1/slo`)
- Create: Grafana JSON + test for slo payload shape

### Task 3: Evaluate package split

**Files:**
- Create: `services/decision-api/src/decision_api/evaluate/{__init__,score,enrichment,pipeline}.py`
- Modify: `main.py` to delegate route
- Verify: evaluate smoke tests

### Task 4: Verify

```bash
cd services/decision-api && PYTHONPATH=src:../shared:../../packages/shared-core:../.. \
  .venv/bin/python -m pytest tests/test_production_profile.py tests/test_decision_outcome.py \
  tests/test_api_endpoints.py::TestEvaluateDecision -q
python3 scripts/release/assert_production_profile.py --env-file infra/deploy/release/fixtures/production-profile.ok.env
```
