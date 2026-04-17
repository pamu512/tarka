# OSS track (#31–#54): closure evidence and sprawl reduction

Use this as a **single checklist** when closing GitHub issues and duplicate PRs. Source DAG: [oss-ship-order-dependencies.md](./oss-ship-order-dependencies.md).

**Convention:** *Merged* = on default line (`ide/v1.2.5-7320` / `master` as applicable). *Open PR* = merge that PR then close the issue with the merge SHA.

---

## Tier 0 — Client + environment baselines

| Issue | Title (short) | Status | Evidence |
|-------|----------------|--------|----------|
| **#43** | Python SDK resilient envelope | **Merged PR #90 area + PR #91/#92** — confirm on branch after merge | `packages/fraud-sdk-python`: `envelope.py`, `evaluate_response.py`, `client.py` kwargs; `docs/docs/sdks/python.md`; tests `test_envelope.py`, `test_decision_client_evaluate.py`; `pytest.ini` `pythonpath` |
| **#44** | TypeScript runtime guards / fail-open | **PR #92** (combined with #43) or standalone branch | `packages/fraud-sdk-typescript/src/runtime.ts`, `DeviceSignalCollector` timeouts, `vitest`, `docs/docs/sdks/typescript.md` |
| **#45** | Mobile attestation taxonomy | **Merged** | PR **#90** merge commit **`3e12842`**: `attestation_taxonomy.py`, `schemas.py`, `main.py` tags + governance, `mobile-attestation-taxonomy.md`, Android/iOS SDK + OpenAPI |
| **#38** | Community vs Pro deployment docs | **PR #93** | `docs/docs/guides/deployment-profiles-community-vs-pro.md`, `deploy/env/*.env.example`, links from `deploy/.env.example` + `docs/docs/index.md` |

---

## Tier 1 — Step contract

| Issue | Title | Status | Evidence |
|-------|--------|--------|----------|
| **#32** | Pipeline step controls | **Branch `ide/github-32-eval-steps-7320`** — open PR to `ide/v1.2.5-7320` (use branch tip SHA when closing) | `eval_steps.py`, `config.py` `EVAL_STEP_*`, `main.py` list/graph_risk/feature/opa/ml steps + `step_trace` in audit, `_graph_upsert_stepped`, `opa_client.py` timeout param, `evaluation-step-controls.md`, `tests/test_eval_steps.py`, Prometheus counters `tarka_eval_step_*` |

---

## Tier 2 — Parallel cores

| Issue | Title | Status | Evidence |
|-------|--------|--------|----------|
| **#31** | Policy DAG shadow / CC routing | **Open** — not implemented as full DAG in this pass | Prior art: `shadow` rules, `experiment_api`, consortium — close only when explicit DAG lands |
| **#33** | Velocity counters + parity | **Largely shipped earlier** | Counter catalog, replay scripts, `AGG_KEY_VERSION`, internal counters API, parity docs — cite merge history on `ide/v1.2.5-7320` (`464a586` era) |

---

## Tier 3 — First integrations

| Issue | Status | Notes |
|-------|--------|--------|
| **#47** Canary cohort audit fields | Open | Needs explicit audit payload fields + UI |
| **#34** Typology layer | Open | Rule aggregation to typologies |
| **#48** Parity verifier job | Partial | `scripts/replay/`, feature-service parity mentioned in issue — align wording to shipped scripts |
| **#49** Graph checkpoint registry | Open | |

---

## Tier 4 — Product slices

| **#46–#51**, **#37**, **#50** | Open | Close when respective PRs merge; avoid duplicate “planning” issues without PR linkage |

---

## Tier 5 — Packaging + ops

| Issue | Status | Evidence |
|-------|--------|----------|
| **#39** Starter typology packs | Open | |
| **#40** Investigation summaries | Partial | `POST /v1/evidence/summary` + tests (investigation-agent) — cite PR/commits for Epic F |
| **#41** Automated scorecards | Partial | Integration scorecards + connector quality — not full “emitter framework” |
| **#42** Graph selective routing | Open | |
| **#52** Promotion policy YAML + CI | Partial | `validate_rule_packs.py` + workflow — extend for ML promotion YAML |
| **#54** Connector quality + probes | **Merged** | PR **#90** / **`3e12842`**: `preflight-probes`, `connector_quality` v1, catalog swimlane, `integration_catalog.py`, OpenAPI, tests |

---

## Tier 6 — Publishing

| **#53** Scorecard → Discussions | Open | |

---

## Sprawl reduction actions

1. **Merge PR #92** (or #91 + #44 separately) then **close #43 and #44** with one comment pointing at the combined merge SHA.
2. **Merge PR #93** then **close #38** with `3eb2c37` (or updated tip).
3. **Merge PR for #32** (branch `ide/github-32-eval-steps-7320`) then **close #32** with the **merge commit SHA** on `ide/v1.2.5-7320` + link to `evaluation-step-controls.md`.
4. **Close #45 and #54** if not already: **`3e12842`** (PR #90).
5. **Supersede duplicate PRs**: if #92 contains #43, close **#91** as superseded.
6. **Epics #1–#12**: close only when acceptance tests + merge SHAs documented (many items already landed on `ide/v1.2.5-7320` — use git log and issue AC).

---

*Last updated: 2026-04 — refresh SHAs after each merge to `ide/v1.2.5-7320`.*
