# Saarthi Pro / OSS — evidence bundle v1 alignment spec

> **Engineering + product spec.** `evidence_bundle_draft` today is **`tarka.evidence_bundle_draft/v0`** (see `services/investigation-agent/src/investigation_agent/evidence_bundle.py`). **v1** finalizes when a shared schema lands in-repo or in a published contract doc. This page defines the **target mapping** so Pro and OSS stay aligned.

## v0 fields (shipped)

| Field | Purpose |
|-------|---------|
| `schema_hint` | `tarka.evidence_bundle_draft/v0` |
| `generated_at` | UTC ISO timestamp |
| `turn_id` | Correlate with chat, logs, feedback |
| `prompt_version` | `COPILOT_PROMPT_VERSION` lineage |
| `playbook_id` | Optional typology playbook |
| `narrative.reply` | Truncated model reply (8k cap) |
| `structured_sections` | FACTS / INFERENCES / … (minus internal `sections_found`) |
| `claims` | Claims trailer (capped) |
| `claims_analysis` | Deterministic / judge hints |
| `source_refs` | Reference cards (capped) |
| `tool_invocation_count` | Count only |

## v1 target (draft contract)

When v1 schema is adopted:

1. **`schema_version`:** replace `schema_hint` with a single **`schema_id`** e.g. `tarka.evidence_bundle/v1` (exact string TBD with schema PR).
2. **Provenance:** add **`agent_build`** (image digest or Pro version) and **`contract_version`** from integration snapshot.
3. **Tool trace:** optional embedded **`tool_trace_redacted`** (hashes or ids only) for audit without full payload duplication—full payloads remain in structured logs if enabled.
4. **Integrity:** optional **`content_sha256`** over canonical JSON subset for export pipelines.
5. **PII tier:** optional **`redaction_level`** enum (`none` / `analyst_view` / `export_safe`) set by policy.
6. **Backward compatibility:** v1 consumers MUST accept v0 payloads during migration; agent may dual-emit `schema_id` + legacy `schema_hint` for one minor release.

## Implementation checklist

- [x] Update `build_evidence_bundle_draft` + OpenAPI for chat response (`dual` default).
- [x] Document in [CHANGELOG_INTEGRATION](CHANGELOG_INTEGRATION.md) (chat companion bullet).
- [x] JSON Schema in [`contracts/schemas/tarka-evidence-bundle-v1.schema.json`](../../../contracts/schemas/tarka-evidence-bundle-v1.schema.json); unit tests in `tests/test_evidence_bundle_v1.py`.

## Related

- [Investigation Agent Project](../projects/investigation-agent-project.md)
- [Saarthi Pro roadmap](saarthi-pro-roadmap.md)
