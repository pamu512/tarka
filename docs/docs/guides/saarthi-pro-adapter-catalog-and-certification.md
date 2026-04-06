# Saarthi Pro — adapter catalog & certification (internal)

> **Internal draft.** Populate **Named integration profiles** as you ship maintained adapters. Golden **profile names** below are **conformance vocabulary** (CI), not SKUs by themselves.

## Golden integration profiles (reference CI)

These names match the investigation-agent CI job **`test-investigation-agent-golden-matrix`** and `tests/test_integration_golden_profiles.py`. They describe **which upstream base URLs are set** and **`COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM`**—i.e. which tools appear on the **model tool list**.

| Profile id | Meaning (upstream + hide flag) |
|------------|--------------------------------|
| `full` | Case + decision + graph URLs set; hide-without-upstream **on** → full tool surface (subject to env disables). |
| `no_graph` | Graph URL empty → graph-family tools suppressed when hide is on. |
| `no_case` | Case URL empty → case-family tools suppressed. |
| `no_decision` | Decision URL empty → decision-family tools suppressed. |
| `case_only` | Only case URL set; graph + decision empty → combined suppression set. |
| `legacy_visible` | Case set, graph + decision empty, hide **off** → tools still listed; runtime errors if called (legacy parity). |

**Use in sales engineering:** “Certified for profile **`no_graph`**” means we test and maintain the adapter with graph upstream absent and default hide behavior—**not** that the customer lacks a graph product, only that the copilot is not wired to it.

## Certification levels (suggested mapping)

Map to [adapter-first tiers](saarthi-pro-adapter-strategy-and-pricing.md) without implying legal warranty:

| Level | Typical tier | Technical gate (illustrative) |
|-------|----------------|--------------------------------|
| **Conformance — smoke** | Runtime + support (customer adapter) | `scripts/ci/check_integration_contract.py` green against deployed agent URL. |
| **Conformance — golden** | Certified adapter | Agreed subset of golden profiles green in **customer UAT** (or Pro staging with customer API mocks), plus documented `INTEGRATION_PROFILE_ID`. |
| **Conformance — sustained** | Adapter + SLA | Above + quarterly re-run or hook in customer CI; release notes on customer API bumps per [change policy](saarthi-customer-api-change-policy.md). |

## Named integration profiles (reference + SKU placeholders)

Use these **`INTEGRATION_PROFILE_ID`** values in config and in order forms. **Reference** rows ship with OSS; **SKU placeholders** are naming patterns for Pro-maintained adapters (replace `{customer}` before external use).

| `integration_profile_id` | Stack / wiring (internal) | Golden profiles to certify | Adapter / image pointer |
|----------------------------|---------------------------|----------------------------|-------------------------|
| `tarka_reference_v1` | Default OSS profile: case + decision + graph URLs set (typical local Compose) | `full` | Monorepo `services/investigation-agent`; image: `services/investigation-agent/Dockerfile` |
| `tarka_case_decision_no_graph_v1` | Case + decision APIs; **no** `GRAPH_SERVICE_URL` (hide tools without upstream **on**) | `no_graph` | Same agent binary; env-only profile |
| `tarka_case_only_v1` | Only `CASE_API_URL`; graph + decision empty | `case_only` | Narrow integration / phased rollout |
| `tarka_legacy_tool_visibility_v1` | Case only but `COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM=false` (tools visible, calls may error) | `legacy_visible` | Legacy parity; document risk in runbook |
| `tarka_no_case_audit_v1` | Decision + graph; case URL empty (audit-heavy, no queue tools) | `no_case` | Rare; document which tools are suppressed |
| `{customer}_maintained_v1` | **Placeholder** — customer SoR APIs behind Pro-maintained adapter | Agreed per SOW (e.g. `full` + `no_graph`) | Private adapter repo or sidecar image name |
| `{customer}_maintained_sidecar_v1` | HTTP adapter sidecar + agent with narrowed upstream URLs | Same as row above | e.g. `registry.example.com/acme/saarthi-adapter:1.0.0` |

**Adding a row:** copy the `{customer}_*` pattern; set golden profiles to the subset run in customer UAT; link the adapter package or image in the last column.

## Related

- [Investigation agent integration contract](investigation-agent-integration-contract.md)
- [Saarthi Pro roadmap](saarthi-pro-roadmap.md) · [certification checklist](saarthi-pro-certification-checklist.md) · [adapter SOW template](saarthi-pro-adapter-sow-template.md)
- Cookiecutter: `templates/cookiecutter-investigation-integration-adapter/`
