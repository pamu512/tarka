# Saarthi Pro agent — release record

Update this file (or equivalent in the Saarthi-pro repo) **on every tagged release**. Keep in sync with [CHANGELOG_INTEGRATION](../../docs/docs/guides/CHANGELOG_INTEGRATION.md).

## Current release (template — fill when tagging)

| Field | Value |
|-------|--------|
| **Saarthi Pro agent image version** | `0.1.0` |
| **OCI image** | `saarthi-pro-agent:0.1.0` (replace with registry path) |
| **fraud-stack git SHA** | `REPLACE_WITH_git_rev_parse_HEAD` |
| **Integration contract** | `1.1.0` (must match `integration_contract.py` at the SHA above) |
| **Default `INTEGRATION_PROFILE_ID`** | `tarka_reference_v1` (customer-specific profiles: [adapter catalog](../../docs/docs/guides/saarthi-pro-adapter-catalog-and-certification.md)) |

## Verification

1. `GET /v1/integration` → `contract_version` equals the value in this table.
2. `python scripts/ci/check_integration_contract.py --base-url http://<host>:8006`
3. Image labels: `docker inspect <image> --format '{{json .Config.Labels}}' | jq` → check `com.tarka.fraud_stack.git_sha`, `com.saarthi.pro.version`.

## History

| Pro agent ver | fraud-stack SHA | contract_version | Notes |
|---------------|-----------------|------------------|--------|
| 0.1.0 | *(initial)* | 1.1.0 | First documented standalone image from `distributions/saarthi-pro-agent`. |
