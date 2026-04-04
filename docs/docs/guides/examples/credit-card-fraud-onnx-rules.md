# Example: Classic payment fraud — rules + ONNX autoencoder

**Goal:** Show a high-risk payment evaluation with **`inference_context`**, rule hits, and optional **ML scoring** via `ml-scoring` (heuristic by default; **ONNX** when configured).

## 1. Start services

**Option A — Lite** (heuristic ML only, no separate `ml-scoring` container):

```bash
docker compose -f deploy/docker-compose.lite.yml up -d --build
```

Point Decision API at ML service only if you run **`ml-scoring`** separately (see Option B).

**Option B — Core + ML** (from repo root, under `deploy/`):

```bash
docker compose -f docker-compose.yml --profile core --profile ml up -d --build
```

Set **`ML_SCORING_URL=http://ml-scoring:8005`** on `decision-api` (already wired in full `docker-compose.yml` when profiles include ml).

## 2. ONNX (optional)

See [ONNX model integration](../onnx-model-integration.md). Quick path:

1. Build `ml-scoring` with optional `onnx` extra or install `onnxruntime` in the image.
2. Mount a model and set **`ONNX_MODEL_PATH`** (and **`DISABLE_ML=false`**).

Without ONNX, `ml-scoring` still returns **heuristic + explainability** signals usable by the Decision API.

## 3. Evaluate a “card-not-present” style event

High amount + velocity + risky device flags:

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "event_type": "payment",
    "entity_id": "card-user-001",
    "payload": {
      "amount": 9200,
      "currency": "USD",
      "merchant_mcc": "5411",
      "event_count_5m": 8,
      "event_count_1h": 35,
      "event_count_24h": 120,
      "is_new_device": true,
      "is_vpn": true,
      "hour_of_day": 3
    },
    "device_context": {
      "device_id": "web-abc",
      "platform": "web",
      "signals": {
        "is_emulator": false,
        "is_vpn": true,
        "is_spoofed_location": false,
        "is_bot": false,
        "is_repackaged": false,
        "webdriver_detected": false,
        "headless_detected": false,
        "automation_detected": false,
        "vpn_interface_detected": true,
        "mock_location_detected": false,
        "timezone_geo_mismatch": true,
        "canvas_fp_hash": null,
        "webgl_renderer": null,
        "screen_res": "1920x1080",
        "touch_support": false,
        "battery_api_present": true,
        "language": "en-US",
        "platform_version": null,
        "captcha": null,
        "audio_fp_hash": null,
        "connection_type": null,
        "device_memory": 8,
        "hardware_concurrency": 8,
        "color_depth": 24,
        "timezone": "UTC",
        "timezone_offset": 0,
        "do_not_track": null,
        "cookie_enabled": true,
        "local_storage_available": true,
        "session_storage_available": true,
        "indexed_db_available": true,
        "max_touch_points": 0,
        "pdf_viewer_enabled": null
      },
      "attestation": null,
      "behavior": null
    }
  }'
```

Inspect **`inference_context`** (tier, **`driver_reasons`**, velocity), **`recommended_action`**, **`rule_hits`**, and **`ml_score`** if ML URL is configured.

## 4. Rules

JSON rules live under `services/decision-api/rules/`. Adjust thresholds via env on Decision API (`DENY_THRESHOLD`, `REVIEW_THRESHOLD`) per [`deployment.md`](../deployment.md).

## 5. Accuracy / datasets

For **reproducible precision/recall** on **synthetic** labeled data, use **`POST /v1/simulation/run`** and **`POST /v1/simulation/benchmark/vertical`** (see [shadow-and-ab-testing.md](../shadow-and-ab-testing.md)). Public Kaggle-style benchmarks are **not** bundled; export features in your notebook and POST to **`/v1/decisions/evaluate`** in batch if you need offline scoring.
