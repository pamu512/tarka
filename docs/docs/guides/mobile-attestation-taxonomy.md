# Mobile attestation taxonomy (Android / iOS)

**Purpose:** One shared vocabulary for **`device_context.attestation`** so rules, audits, and governance see the same signals on **Play Integrity** and **App Attest**.

## Canonical `provider` values

| Value | Client |
| ----- | ------ |
| `play_integrity` | Android (`fraud-sdk-android`) |
| `app_attest` | iOS (`fraud-sdk-ios`) |

## Canonical `status`

| Status | Meaning |
| ------ | ------- |
| `obtained` | Non-empty token was returned by the platform API. |
| `absent` | No attestation block is sent (caller omitted it). |
| `failed` | Client attempted attestation but could not obtain a token. |
| `disabled` | SDK flag turned off (`enablePlayIntegrity` / `enableAppAttest` false). |
| `unsupported` | OS or hardware does not support the API (e.g. App Attest not supported). |

## Canonical `failure_reason` (when `status` is `failed` or `unsupported`)

| Code | Typical cause |
| ---- | ------------- |
| `client_error` | Generic catch-all for client-side failures. |
| `token_unavailable` | Play Integrity / App Attest returned no usable token. |
| `challenge_failed` | Could not fetch or use `/v1/attestation/challenge`. |
| `integrity_api_error` | Play Integrity API error. |
| `attest_not_supported` | App Attest not supported on device. |

## Client `confidence_tier` (hint only)

Optional string on the attestation object: `none` \| `low` \| `medium` \| `high`.

- **`obtained`** tokens default to **`medium`** at the client (server verification may raise tier).
- **`failed`** / **`unsupported`** should use **`none`** or **`low`**.

Downstream tags (Decision API) include `sdk:attestation_*` — see server normalization in `DeviceContextIn` validators.

## Governance linkage

- Ops bundle: `GET /v1/ops/governance` includes **`mobile_attestation_taxonomy`** (path to this doc and schema version).
- Inference contract: `inference_schema_version` applies to **`inference_context`**; attestation payloads are versioned separately as **`attestation_schema_version` = 1**.
