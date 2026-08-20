# Cookiecutter: investigation integration adapter

Scaffolds a Python package for an HTTP adapter: client stubs, profile id placeholder, and smoke test. Replace stubs with real mapping logic against the customer’s Case / Graph / Decision APIs. This template is OSS reference only.

## Prerequisites

- Python 3.11+
- [Cookiecutter](https://cookiecutter.readthedocs.io/) 2.x: `pip install cookiecutter`

## Usage

From the repository root (or any machine with this template path):

```bash
cookiecutter templates/cookiecutter-investigation-integration-adapter --no-input \
  adapter_slug=acme_fraud_adapter \
  package_name=acme_fraud_adapter \
  customer_display_name="Acme Bank" \
  integration_profile_id=acme_case_graph_v1
```

Or run interactively (omit `--no-input` and flags) to answer prompts from `cookiecutter.json`.

## After generate

1. Start the upstream mock (repo root):

```bash
python scripts/integration_adapter_mock/server.py --port 18080
```

2. Point the scaffold at the mock and run smoke tests:

```bash
export CASE_API_URL=http://127.0.0.1:18080
export GRAPH_SERVICE_URL=http://127.0.0.1:18080
export DECISION_API_URL=http://127.0.0.1:18080
cd <generated_dir> && pip install -e '.[dev]' && pytest -q
```

`example_health_probe()` should return ``status: "ok"`` with case/graph/decision checks green.

3. Set `INTEGRATION_PROFILE_ID` in deployment config to match `integration_profile_id` (see [Investigation agent integration contract](../../docs/docs/guides/investigation-agent-integration-contract.md)).
4. Extend HTTP mapping in `adapter.py` for customer-specific fields; keep the mock path as a regression baseline.
5. Add contract/golden tests in your CI; mirror vocabulary from this repo’s `.github/workflows/ci.yml` job **`test-investigation-agent-golden-matrix`**.
6. Follow [Customer API change policy](../../docs/docs/guides/investigation-agent-integration-contract.md) for versioning and breaking changes.

`package_name` must be a valid Python import name (letters, digits, underscores). `adapter_slug` is the directory name; keep them aligned unless you have a strong reason not to.
