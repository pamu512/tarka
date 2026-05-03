# API Versioning Strategy

Tarka uses **path-based major API versioning** for service contracts:

- Current stable contract: `/v1/...`
- Future breaking contract: `/v2/...` (introduced alongside migration guidance)

## Compatibility Rules

- Non-breaking additions (new optional fields, new endpoints) may ship within `v1`.
- Breaking response/request changes require a new major path version.
- Existing `v1` endpoints remain supported for an announced migration window.

## Deprecation Workflow

1. Mark endpoint/field as deprecated in docs and OpenAPI descriptions.
2. Publish migration notes and parity examples.
3. Enforce sunset date in release planning.
4. Remove deprecated contract only in next major version.

## Testing and CI Expectations

- OpenAPI contract validation remains required in CI.
- New major versions must include compatibility and migration tests.
- Consumer-facing SDKs should pin and document supported API major versions.

