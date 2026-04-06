# Investigation Copilot — integration contract changelog

Tracks **breaking or material** changes to `GET /v1/integration`, tool **names**, **families**, and **upstream suppression** rules. Adapters and Saarthi Pro conformance suites should pin **`contract_version`** from the live snapshot.

## 1.1.0 (2026-04)

- **Bump `INTEGRATION_CONTRACT_VERSION` to `1.1.0`.**
- **`COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM`** (default `true`, field `copilot_hide_tools_without_upstream`): tools whose upstream base URL is empty are **omitted** from the model tool list and listed under `tools.upstream_suppressed` in the integration snapshot.
- Snapshot **`tools.env_disabled`** renamed to **`tools.disabled_effective`** (union of env-disabled and upstream-suppressed). Clients parsing old key should migrate.
- **`upstream_runtime_notes.hide_tools_without_upstream`** documents the flag.
- **Docs & conformance tooling:** per-profile golden tests (`services/investigation-agent/tests/test_integration_golden_profiles.py`) and CI matrix job `test-investigation-agent-golden-matrix`; adapter cookiecutter `templates/cookiecutter-saarthi-pro-adapter/`; draft customer API / contract process norms in [saarthi-customer-api-change-policy.md](saarthi-customer-api-change-policy.md).
- **Saarthi Pro commercial playbooks (docs only):** Phase 1–3 operational templates and product specs indexed from [saarthi-pro-roadmap.md](saarthi-pro-roadmap.md) (upgrade, release notes, support tiers, certification, SSO/SCIM, DPA, VPC, runbooks, SOW, evidence v1 alignment spec, analytics, economics, legal exhibit outlines)—no change to integration JSON wire format.
- **Chat API companion (not `/v1/integration`):** `evidence_bundle_draft` default **`COPILOT_EVIDENCE_BUNDLE_FORMAT=dual`** adds **`schema_id`** `tarka.evidence_bundle/v1` with `contract_version`, `tool_trace_redacted`, `content_sha256`, optional `agent_build` (`AGENT_BUILD_ID`), and `redaction_level` (`COPILOT_EVIDENCE_REDACTION_LEVEL`); legacy **`schema_hint`** retained. Optional **`COPILOT_ANALYTICS_ENABLED`** emits PII-minimized `copilot.turn.completed` / `copilot.feedback.submitted` to log or HTTP webhook. Schema: [`contracts/schemas/tarka-evidence-bundle-v1.schema.json`](../../../contracts/schemas/tarka-evidence-bundle-v1.schema.json).

## 1.0.0

- Initial published contract: `GET /v1/integration`, `integration` on `GET /v1/health`, `profile_id`, `families_enabled`, `maker_checker` metadata.
