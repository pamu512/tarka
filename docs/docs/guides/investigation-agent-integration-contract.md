# Investigation Copilot — integration contract (OSS reference)

This document describes the **machine-readable integration surface** of `services/investigation-agent`, aligned with an **adapter-first** commercial strategy (e.g. Saarthi Pro): third parties implement **their** APIs behind a stable **logical tool surface** and declare a **`profile_id`**.

> **Not a legal or procurement artifact.** Use for engineering parity, smoke tests, and RFP technical appendices.

## Contract version

- **`INTEGRATION_CONTRACT_VERSION`** is defined in code (`integration_contract.py`) and returned by the API. Current line: **1.1.x** (see [CHANGELOG_INTEGRATION](CHANGELOG_INTEGRATION.md)).
- **Bump the minor/patch** when adding tools or changing semantics; **bump major** when renaming tools or changing upstream expectations in a breaking way for adapters.
- **JSON Schema (CI / validation):** [`contracts/schemas/investigation-agent-integration-snapshot.schema.json`](../../../contracts/schemas/investigation-agent-integration-snapshot.schema.json)

## Discovery endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/integration` | Full snapshot: `contract_version`, `profile_id`, upstream flags, enabled tools, families, maker–checker hints. **No raw URLs** (avoids leaking internal endpoints). |
| `GET /v1/health` | Includes the same object under **`integration`** (plus `copilot_features`, governance profile, etc.). |

## Configuration

| Env / setting | Effect |
|---------------|--------|
| `INTEGRATION_PROFILE_ID` / `integration_profile_id` | Customer- or Pro-defined label (e.g. `acme_case_api_v1`). Default `tarka_reference_v1`. |
| `CASE_API_URL`, `DECISION_API_URL`, `GRAPH_SERVICE_URL` | Drive `upstream_configured.*` booleans. When empty, affected tools are **hidden from the model** if `COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM=true` (default). |
| `COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM` / `copilot_hide_tools_without_upstream` | Default **true**: omit tool definitions that require a missing upstream URL (cleaner adapter profiles). Set **false** for legacy behavior (tools visible; calls return `{"error":...}`). |
| `COPILOT_DISABLED_TOOLS` | Removes tools from the enabled list (union with upstream suppression). |
| Snapshot fields | **`tools.disabled_effective`**: env-disabled ∪ upstream-suppressed. **`tools.upstream_suppressed`**: names hidden due to missing upstream (when hide flag true). |

**Maker–checker:** sensitive tools are hidden **per request** when `COPILOT_REVIEWER_SECRET` is set and the client omits `x-reviewer-secret`. The snapshot reports `maker_checker` metadata but still lists sensitive tool **names** as configured—adapters should treat exposure as **conditional**.

## Tool families (logical)

Families group tools for mapping to foreign systems:

| Family | Tools (reference build) | Typical upstream |
|--------|-------------------------|------------------|
| **case** | `get_case`, `list_cases`, `compare_entity_queue_snapshot` | Case / alert / queue API |
| **graph** | `subgraph`, `subgraph_with_velocity`, `get_entity_tags` | Graph / link service |
| **decision** | `get_decision_audit`, `get_entity_velocity`, `subgraph_with_velocity` (overlay) | Decision / scoring / audit store |
| **batch** | `get_batch_profile`, `query_batch_rows`, `aggregate_batch_column` | Agent-local tabular ingest (not customer case API) |
| **knowledge** | `search_knowledge` | Agent-local RAG (memos) |
| **labels** | `export_outcome_labeled_dataset`, `ingest_labeled_rows`, `get_stored_labeled_dataset` | Case-api drafts (Tarka-shaped) |
| **replay** | `run_replay_ab_comparison` | Decision replay API |

Pro adapters for **non-Tarka** stacks map these families to customer endpoints; not every deployment enables every family.

## Conformance checks

- **Unit tests:** `services/investigation-agent/tests/test_integration_contract.py`
- **Live smoke (optional):** from repo root, with agent running:

```bash
python scripts/ci/check_integration_contract.py --base-url http://localhost:8006
```

Add `--api-key` if the deployment requires it.

## Minimal upstream mock (local dev)

- **[`scripts/integration_adapter_mock/`](../../../scripts/integration_adapter_mock/)** — stdlib HTTP server with stub Case / Graph / Decision paths so the agent can run against a single port without the full stack.

## Related

- [CHANGELOG_INTEGRATION](CHANGELOG_INTEGRATION.md)
- [Saarthi customer API change policy](saarthi-customer-api-change-policy.md) (notice windows, joint certification, contract vs customer API versions)
- Adapter cookiecutter template: [`templates/cookiecutter-investigation-integration-adapter/`](../../../templates/cookiecutter-investigation-integration-adapter/) (OSS scaffold for HTTP adapters; vendor-maintained packaging → private [Saarthi-pro](https://github.com/pamu512/Saarthi-pro))
- [Saarthi Pro roadmap](saarthi-pro-roadmap.md) · [distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md) · [adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md)

- [Saarthi Pro adapter strategy & pricing (internal draft)](saarthi-pro-adapter-strategy-and-pricing.md)
- [Investigation Copilot — intended use & data flows](investigation-agent-intended-use-and-data-flows.md)
- [Investigation Agent Project](../projects/investigation-agent-project.md)
