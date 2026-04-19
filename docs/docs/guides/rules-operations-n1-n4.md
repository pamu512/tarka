# Rule operations N1–N4 (no-code, governance, telemetry)

This guide maps backlog items **N1–N4** from [v1.2.5 execution backlog](./v1.2.5-execution-backlog-status.md) to concrete behavior in the Decision API and Rules UI.

## N1 — No-code rule builder

- **UI:** `frontend/src/pages/Rules.tsx` — visual pack editor, templates, simulation, **field catalog** (grouped feature names), **export all packs as JSON**.
- **Validation:** `scripts/policy/validate_rule_packs.py` and `decision_api.rule_pack_validation` (CI-friendly structural checks).

## N2 — Maker–checker for rule mutations

- **Server:** When `RULE_GOVERNANCE_SECRET` is set in the Decision API environment, every **mutating** call under `/v1/rules` must include header **`X-Rule-Governance-Secret`** with the same value. Applies to create/update/delete packs, add/remove rules, vertical install, and pack mode changes. Read-only routes (`GET`, change-log, telemetry, shadow read) are unchanged.
- **UI:** The Rules page stores an optional governance token in `localStorage` as `tarka.rule_governance_secret` and sends it on mutations via the API client.

## N3 — Per-rule hit telemetry (in-process)

- **Engine:** Each time a JSON rule or tag-rule fires, `decision_api.json_rules` increments an in-memory counter keyed by `(pack file, rule id, kind)`.
- **API:** `GET /v1/rules/telemetry` returns `{ since_unix, total_hits, unique_keys, rows[] }` for dashboards and the Rules UI “Refresh rule telemetry” control.
- **Scope:** Counts reset on API process restart (same pattern as other in-process SLO counters).

## N4 — Aggregate rule telemetry in Prometheus

- Counter **`tarka_json_rule_hits_total`** (label `service=decision-api`) increments once per rule/tag-rule hit; scrape **`GET /metrics`** on the Decision API.

## Environment

See `deploy/.env.example` — `RULE_GOVERNANCE_SECRET` (optional).
