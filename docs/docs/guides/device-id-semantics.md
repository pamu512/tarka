# `device_id` semantics (SDKs and server)

## What `device_id` is

- **Not** a hardware IMEI/serial from Tarka OSS SDKs.
- A **tenant-agnostic, install-scoped stable string** derived from privacy-preserving inputs (e.g. hashed Android ID, hashed iOS `identifierForVendor`, web fingerprint components).
- Used as **`device_context.device_id`** on `POST /v1/decisions/evaluate` and stored under graph **`Device.external_id`** when graph is enabled.

## Server-side linking (Redis)

When **`REDIS_URL`** is configured, the Decision API:

1. **Fingerprints** — `services/decision-api/src/decision_api/fingerprint_store.py` records a **derived fp_hash** from `device_id` + `platform` + sorted scalar signals → **`sdk:shared_device`** if multiple **entity_id** values share a fingerprint.
2. **Entity links** — `services/decision-api/src/decision_api/entity_link_store.py`:
   - **`fraud:link:device_entity:{tenant}:{device_id}`** — ZSET of **entity_id** seen with this device (recent first).
   - Optional **vendor bridge** from **`metadata`**:
     - `vendor_visitor_id`, `vendor_device_id`, `vendor_install_id` → SET **`fraud:link:vendor:{tenant}:{type}:{id}`** = **entity_id**
   - Injected into **features** for rules: **`linked_entity_ids`**, optional **`vendor_bridge_entity_id`**, tags **`sdk:linked_entities`**, **`sdk:vendor_entity_bridge`**.

## Optional vendor ID bridge

Pass vendor IDs **only** when you have consent and a mapping contract:

```json
"metadata": {
  "vendor_visitor_id": "fp_visitor_abc123"
}
```

The server stores the latest **entity_id** seen with that vendor id. Use for **gradual** migration from a commercial device graph — not as strong as native attestation alone.

## Related

- [TLS pinning and signed requests](./tls-pinning-and-signed-requests.md)  
- [SDK scorecard](./sdk-scorecard-2026-01.md)
