# Example: API bot / credential-stuffing defense

**Goal:** Exercise **device and behavior-style signals**, **velocity** in **`inference_context`**, and awareness of **ingress replay-style** hardening (Redis-backed duplicate detection on the Decision path when configured).

## 1. Stack

Use **lite** compose (Decision + Case + Ingress + UI):

```bash
docker compose -f deploy/docker-compose.lite.yml up -d --build
```

## 2. Bot-like session (no human-like behavior)

Tight velocity + automation hints:

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "event_type": "login",
    "entity_id": "acct-brute-9001",
    "payload": {
      "event_count_5m": 40,
      "event_count_1h": 200,
      "event_count_24h": 800,
      "is_bot": true,
      "is_emulator": true,
      "webdriver_detected": true,
      "headless_detected": true,
      "hour_of_day": 2
    },
    "device_context": {
      "device_id": "auto-headless",
      "platform": "web",
      "signals": {
        "is_emulator": true,
        "is_vpn": false,
        "is_spoofed_location": false,
        "is_bot": true,
        "is_repackaged": false,
        "webdriver_detected": true,
        "headless_detected": true,
        "automation_detected": true,
        "vpn_interface_detected": false,
        "mock_location_detected": false,
        "timezone_geo_mismatch": false,
        "canvas_fp_hash": null,
        "webgl_renderer": "Google SwiftShader",
        "screen_res": "800x600",
        "touch_support": false,
        "battery_api_present": false,
        "language": "en-US",
        "platform_version": "HeadlessChrome",
        "captcha": null,
        "audio_fp_hash": null,
        "connection_type": "4g",
        "device_memory": 4,
        "hardware_concurrency": 2,
        "color_depth": 24,
        "timezone": "Etc/UTC",
        "timezone_offset": 0,
        "do_not_track": "1",
        "cookie_enabled": false,
        "local_storage_available": false,
        "session_storage_available": false,
        "indexed_db_available": false,
        "max_touch_points": 0,
        "pdf_viewer_enabled": null
      },
      "attestation": null,
      "behavior": null
    }
  }'
```

Expect elevated **`replay_risk` / tamper-related drivers** when ingress and payload patterns align with configured rules; **`recommended_action`** may suggest step-up or block.

## 3. Credential stuffing pattern

Repeat the same request with **different `entity_id`** but identical **high-velocity** payload shape to simulate many accounts per IP (in production you would vary **`metadata`** / IP-derived fields if your rules use them).

## 4. Client SDK

The **TypeScript** package `@tarka/sdk` can collect **device signals** in-browser for real integrations (see `packages/fraud-sdk-typescript`). This example uses explicit JSON for clarity.

## 5. Ingress

For **OSINT** on abusive IPs (parallel enrichment), use Integration Ingress (port **8003** in lite):

```bash
curl -s -X POST http://localhost:8003/v1/osint \
  -H "Content-Type: application/json" \
  -d '{"ip":"198.51.100.10","email":null,"phone":null,"domain":null}'
```

See [adding-osint-source.md](../adding-osint-source.md) to add providers.
