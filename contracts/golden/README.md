# Golden fixtures — inference and API parity

## `inference-context-v2.example.json`

Canonical **key set** (and example numeric shape) for **`inference_context`** v2 returned by `decision_api.inference_build.build_inference_context` and surfaced on evaluate/audit.

**CI:** `services/decision-api/tests/test_golden_inference.py` asserts every production `build_inference_context` output contains these keys (values may differ by scenario).

## How to extend (calibration work)

1. Add a **new field** to `build_inference_context` + OpenAPI + SDKs.
2. Update this JSON **example** and the pytest allow-list.
3. Prefer **additive** optional fields for minor releases; bump **`schema_version`** for breaking semantics.

## Cross-SDK parity

- **Python / TypeScript SDKs** should expose the same logical fields as `contracts/openapi/decision-api.yaml` **`InferenceContext`**.
- Add **device-context** golden tests separately under `contracts/json-schema/` when expanding SDK collectors.
