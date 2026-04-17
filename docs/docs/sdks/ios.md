# iOS SDK (Swift)

**Package:** `packages/tarka-ios` (Swift Package Manager)

The Swift SDK sends **`device_context`** with **`platform: "ios"`** and signals aligned with the Decision API and [device-context JSON schema](../../contracts/json-schema/device-context.json).

**Full README:** [`packages/tarka-ios/README.md`](../../../packages/tarka-ios/README.md)

## Highlights

- **`DecisionClient`** — async `evaluate`, `requestChallenge`, `getAudit`
- **`DeviceSignalCollector`** — simulator detection, VPN interface heuristics, **`identifierForVendor`**-based stable **`device_id`**
- **App Attest** — bring your own assertion; attach **`Attestation`** with provider **`app_attest`**

See also: [SDK scorecard](../guides/sdk-scorecard-2026-01.md)
