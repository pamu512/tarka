# Cookiecutter: Saarthi Pro customer adapter

Scaffolds a **private** Python package for a maintained Saarthi Pro adapter: HTTP client stubs, profile id placeholder, and smoke test. Replace stubs with real mapping logic against the customer’s Case / Graph / Decision APIs.

## Prerequisites

- Python 3.11+
- [Cookiecutter](https://cookiecutter.readthedocs.io/) 2.x: `pip install cookiecutter`

## Usage

From the repository root (or any machine with this template path):

```bash
cookiecutter templates/cookiecutter-saarthi-pro-adapter --no-input \
  adapter_slug=acme_fraud_adapter \
  package_name=acme_fraud_adapter \
  customer_display_name="Acme Bank" \
  integration_profile_id=acme_case_graph_v1
```

Or run interactively (omit `--no-input` and flags) to answer prompts from `cookiecutter.json`.

## After generate

1. Set `INTEGRATION_PROFILE_ID` in deployment config to match `integration_profile_id` (see [Investigation agent integration contract](../../docs/docs/guides/investigation-agent-integration-contract.md)).
2. Implement HTTP calls and response mapping in `adapter.py` (and split modules as the adapter grows).
3. Add contract/golden tests in your CI; mirror vocabulary from this repo’s `.github/workflows/ci.yml` job **`test-investigation-agent-golden-matrix`** (profiles: `full`, `no_graph`, `no_case`, `no_decision`, `case_only`, `legacy_visible`).
4. Follow [Saarthi customer API change policy](../../docs/docs/guides/saarthi-customer-api-change-policy.md) for versioning and breaking changes.

`package_name` must be a valid Python import name (letters, digits, underscores). `adapter_slug` is the directory name; keep them aligned unless you have a strong reason not to.
