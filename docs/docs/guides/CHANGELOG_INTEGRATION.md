# Investigation Copilot — integration contract changelog

Tracks **breaking or material** changes to `GET /v1/integration`, tool **names**, **families**, and **upstream suppression** rules. Adapters and Saarthi Pro conformance suites should pin `**contract_version`** from the live snapshot.

## 1.1.0 (2026-04)

- **Bump `INTEGRATION_CONTRACT_VERSION` to `1.1.0`.**
- `**COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM`** (default `true`, field `copilot_hide_tools_without_upstream`): tools whose upstream base URL is empty are **omitted** from the model tool list and listed under `tools.upstream_suppressed` in the integration snapshot.
- Snapshot `**tools.env_disabled`** renamed to `**tools.disabled_effective**` (union of env-disabled and upstream-suppressed). Clients parsing old key should migrate.
- `**upstream_runtime_notes.hide_tools_without_upstream**` documents the flag.
- **Docs & conformance tooling:** per-profile golden tests (`services/investigation-agent/tests/test_integration_golden_profiles.py`) and CI matrix job `test-investigation-agent-golden-matrix`; adapter cookiecutter `templates/cookiecutter-investigation-integration-adapter/`; draft customer API / contract process norms in [saarthi-customer-api-change-policy.md](saarthi-customer-api-change-policy.md).
- **Saarthi Pro commercial playbooks (docs only):** Phase 1–3 operational templates and product specs indexed from [saarthi-pro-roadmap.md](saarthi-pro-roadmap.md) (upgrade, release notes, support tiers, certification, SSO/SCIM, DPA, VPC, runbooks, SOW, evidence v1 alignment spec, analytics, economics, legal exhibit outlines)—no change to integration JSON wire format.
- **Chat API companion (not `/v1/integration`):** `evidence_bundle_draft` default `**COPILOT_EVIDENCE_BUNDLE_FORMAT=dual`** adds `**schema_id**` `tarka.evidence_bundle/v1` with `contract_version`, `tool_trace_redacted`, `content_sha256`, optional `agent_build` (`AGENT_BUILD_ID`), and `redaction_level` (`COPILOT_EVIDENCE_REDACTION_LEVEL`); legacy `**schema_hint**` retained. Optional `**COPILOT_ANALYTICS_ENABLED**` emits PII-minimized `copilot.turn.completed` / `copilot.feedback.submitted` to log or HTTP webhook. Schema: `[contracts/schemas/tarka-evidence-bundle-v1.schema.json](../../../contracts/schemas/tarka-evidence-bundle-v1.schema.json)`.

### Additive surfaces (trunk, April 2026) — still `INTEGRATION_CONTRACT_VERSION` **1.1.0**

No contract bump; clients should ignore unknown JSON fields as usual.

- `**GET /v1/ready`:** Readiness probe — data directory writable for SQLite/RAG; **503** with `not_ready` when checks fail.
- `**GET /v1/setup`:** Config-derived first-run checklist (LLM keys, embeddings/RAG, optional upstream URLs); does not probe external networks.
- `**GET /v1/health`:** May include a `**production`** object (profile flags and `config_ok`) when production diagnostics are enabled. OpenAPI: `[contracts/openapi/investigation-agent.yaml](../../../contracts/openapi/investigation-agent.yaml)`.
- `**POST /v1/chat`:** Optional `**workflow_id`**, `**workflow_params**`, `**playbook_id**`, `**batch_id**` (workflow catalog via `**GET /v1/workflows**`). `**POST /v1/reports/case-summary**` (PDF) and `**POST /v1/reports/turn-bundle**` (Markdown + JSON) for analyst handoff.
- `**POST /v1/evidence/summary` (OSS #40):** Deterministic analyst summary from the same chat-shaped fields as `/v1/chat` (no LLM round). Response includes `citations` with `resolves_to` (trace, case, rule, typology anchors), `next_actions` from optional `typology_breakdown`, optional `decision_audit` anchors on the first citation, and filtered `proposed_next_actions` (`kind=automated_side_effect` only when the action `id` matches `EVIDENCE_SUMMARY_AUTOMATED_ACTION_ALLOWLIST`). OpenAPI: `[contracts/openapi/investigation-agent.yaml](../../../contracts/openapi/investigation-agent.yaml)`. Human index: [API Reference — Investigation Agent](../api-reference.md#investigation-agent).
- **Collaboration chat** (`investigation_agent.chat_bridge`, not part of `GET /v1/integration`): embedded sub-app on investigation-agent (`**/v1/chat/…`**); forwards enriched messages to `**POST /v1/chat**` with `**messages_preprocessed=true**`. OpenAPI and path notes: `[contracts/openapi/collaboration-chat-bridge.yaml](../../../contracts/openapi/collaboration-chat-bridge.yaml)`.

## 1.0.0

- Initial published contract: `GET /v1/integration`, `integration` on `GET /v1/health`, `profile_id`, `families_enabled`, `maker_checker` metadata.