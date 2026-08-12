# Uncommitted work triage (2026-08-12)

Classification before commit of the depth / AI / honesty wave.

## Discard / never commit (local artifacts)

| Path | Reason |
|------|--------|
| `.tarka-micro-e2e/` | Local e2e DB + list JSON |
| `data/` | Local `decision_logs` / analytics DBs |
| `test-results/` | Playwright/UI artifacts |
| `rules/enforcement_delivery.jsonl` | Duplicate / stray; canonical under `services/decision-api/rules/` |

These are gitignored going forward.

## Keep and ship

- **Honesty / productionization:** STUB_REGISTER close, desk-strict trend, SAR XML depth floor, invent-success fail-closed (bot, graph signals, mule demo gate, demo-burst OSINT, rule-engine demo fallback), compose trend-tick, runbook
- **AI ops:** analytics `trend_*`, decision-api `trend_agent_api`, orchestrator watch enqueue, OpsCalibration / AgentRun UI, OpenAPI, tests
- **Depth / vertical:** depth engines/fusion, ring/lifecycle, marketplace KYB, chargeback bridges, vendor plugins, golden fixtures + tests
- **Investigation:** agent_run_store, context_assembler, citation/tool hardening + tests
- **Specs/plans:** `docs/superpowers/specs|plans/2026-08-11*` and `2026-08-12*`
- **Docs:** this guide + [feature-data-flows](feature-data-flows.md) + productionization runbook

## Needs follow-up (shippable but watch)

| Item | Note |
|------|------|
| `tools/shadow` submodule dirty | Specialized stubs raise `NotImplementedError` — commit/push in `pamu512/shadow` then bump submodule SHA, or leave dirty locally |
| Vertical golden corpora | Large fixtures — keep; CI time may grow |
| `services/decision-api/rules/calibration_data/y_labels_golden-tenant.json` | Fixture labels — keep if tests reference |
| Frontend mocks still present | SR-13 **Done (Degrade)** — intentional |

## Do not treat as incomplete invent-data

Depth/vertical modules are mounted via `main.py` / evaluate pipeline and covered by golden tests — integrate as one commit set with honesty + AI ops.
