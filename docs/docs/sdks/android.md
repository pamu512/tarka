# Android SDK (Kotlin)

**Package:** `packages/tarka-android` (Gradle library module `tarka-sdk`)

The Kotlin SDK sends **`device_context`** with **`platform: "android"`** and signals aligned with the Decision API and [device-context JSON schema](../../contracts/json-schema/device-context.json).

**Full README:** [`packages/tarka-android/README.md`](../../../packages/tarka-android/README.md)

## Highlights

- **`DecisionClient`** — `POST /v1/decisions/evaluate`, `POST /v1/attestation/challenge`, `GET /v1/audit/{trace_id}`
- **`DeviceSignalCollector`** — emulator heuristics, VPN interface, installer / repackage hint, mock-location developer setting, stable **`device_id`** (SHA-256 of install-scoped inputs)
- **Play Integrity** — bring your own token; attach **`Attestation`** with provider **`play_integrity`**

See also: [SDK scorecard](../guides/sdk-scorecard-2026-01.md)
