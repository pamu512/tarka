# {{ cookiecutter.customer_display_name }} — Saarthi Pro adapter

**Integration profile id:** `{{ cookiecutter.integration_profile_id }}` — set `INTEGRATION_PROFILE_ID` to this value in the investigation-agent deployment that uses this adapter (or the sidecar that fronts it).

{{ cookiecutter.project_description }}

## Layout

- `src/{{ cookiecutter.package_name }}/adapter.py` — map customer APIs ↔ Saarthi tool payloads (replace stubs).
- `tests/` — extend with contract tests against customer sandboxes or recorded fixtures.

## References (Tarka / Saarthi OSS reference repo)

- [Investigation agent integration contract](https://github.com/tarka-ai/fraud-stack/blob/main/docs/docs/guides/investigation-agent-integration-contract.md) (adjust path if your fork differs)
- [Customer API change policy](https://github.com/tarka-ai/fraud-stack/blob/main/docs/docs/guides/saarthi-customer-api-change-policy.md)
- Upstream mock for local dev: `scripts/integration_adapter_mock/` in the fraud-stack repo
