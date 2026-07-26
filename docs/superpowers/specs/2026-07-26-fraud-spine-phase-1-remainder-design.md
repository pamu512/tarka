# Fraud spine Phase 1 remainder — design

Approved 2026-07-26. Completes Phase 1 after Phase 0 + Phase 1 core.

## Scope

1. **Production fail-closed profile** — env asserts + CI fixture + governance checklist item
2. **Degraded-decision SLO surface** — `/v1/slo` counters + Grafana JSON
3. **Evaluate pipeline split** — `decision_api/evaluate/` with `run_evaluate_decision`; HTTP stays in `main.py`

## A — Production profile

- Module: `decision_api/production_profile.py` → `check_production_env(env) -> list[str]`
- Fail when: `ALLOW_INSECURE_NO_AUTH` soft-open, empty `API_KEYS`, `TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY` not true
- Startup: if `TARKA_DEPLOYMENT_PROFILE=production`, refuse boot on errors
- CI: `scripts/release/assert_production_profile.py` against good + bad fixtures
- Checklist item: `production-auth-idempotency-fail-closed` (`ci_required: true`)

## B — Degraded SLO

- `Metrics.custom_counters_matching(prefix)` (or equivalent) on shared observability
- `GET /v1/slo` includes `degraded_decisions: { total, by_reason }`
- Grafana: `infra/deploy/observability/grafana/.../tarka-degraded-decisions.json`

## C — Evaluate split

- `decision_api/evaluate/score.py` — blend / fallback / runtime status helpers
- `decision_api/evaluate/pipeline.py` — `run_evaluate_decision(...)` (body moved from main)
- `decision_api/evaluate/enrichment.py` — stable import path for enrichment wrappers (delegates to main until circuits move)
- `main.py` registers route, calls `bind_main(sys.modules[__name__])`, delegates to pipeline
- Pipeline binds helpers (and `evaluate_json_rules`) from main so existing test patches on `decision_api.main.*` keep working

## Out of scope

Phase 2 CQRS, frontend shrink, flipping CI global `ALLOW_INSECURE_NO_AUTH`.
