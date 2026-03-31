# ML Scoring

The ML Scoring service provides real-time model inference for fraud detection. It supports an ONNX model registry with versioned deployments, A/B traffic splitting, and automatic heuristic fallback when no trained model is available.

**Port:** 8005
**Version:** 3.0.0
**Framework:** Python / FastAPI

---

## Endpoints

### Health Check

```
GET /v1/health
```

**Response:**

```json
{
  "status": "ok",
  "disable_ml": false,
  "model_version": "heuristic-v1",
  "onnx_loaded": true,
  "registry_models": 2
}
```

---

### Score

Score a set of features for fraud risk. Returns a score between 0 and 100.

```
POST /v1/score
```

**Request:**

```json
{
  "tenant_id": "acme",
  "entity_id": "user-42",
  "event_type": "payment",
  "features": {
    "amount": 499.99,
    "hour_of_day": 14,
    "is_new_device": false,
    "is_vpn": true,
    "is_emulator": false,
    "is_bot": false,
    "transaction_count_24h": 3,
    "distinct_countries_7d": 1,
    "account_age_days": 120
  }
}
```

**Response (ONNX model):**

```json
{
  "score": 32.5,
  "model_version": "fraud-gbm/v1+onnx"
}
```

**Response (heuristic fallback):**

```json
{
  "score": 20.0,
  "model_version": "heuristic-v1"
}
```

---

### List Models

List all registered model versions with their status and stats.

```
GET /v1/models
```

**Response:**

```json
{
  "models": [
    {
      "model_name": "fraud-gbm",
      "version": 1,
      "traffic_weight": 80,
      "active": true,
      "has_onnx": true,
      "total_inferences": 15234,
      "avg_latency_ms": 2.31,
      "metadata": {
        "description": "Gradient boosted model trained on payment fraud data",
        "training_date": "2026-03-15",
        "auc": 0.94,
        "traffic_weight": 80,
        "active": true
      }
    },
    {
      "model_name": "anomaly-iforest",
      "version": 1,
      "traffic_weight": 20,
      "active": true,
      "has_onnx": false,
      "total_inferences": 3801,
      "avg_latency_ms": 1.85,
      "metadata": {
        "description": "Isolation forest for anomaly detection",
        "training_date": "2026-03-20",
        "traffic_weight": 20,
        "active": true
      }
    }
  ]
}
```

---

### Activate Model Version

Set a specific version as the sole active version for a model. All traffic is routed to this version.

```
POST /v1/models/{name}/activate
```

**Request:**

```json
{ "version": 1 }
```

**Response:**

```json
{
  "ok": true,
  "model": "fraud-gbm",
  "active_version": 1
}
```

---

### Model Stats

Get per-version inference statistics for a model.

```
GET /v1/models/{name}/stats
```

**Response:**

```json
{
  "model": "fraud-gbm",
  "versions": [
    {
      "version": 1,
      "active": true,
      "traffic_weight": 100,
      "total_inferences": 15234,
      "avg_latency_ms": 2.31,
      "last_used": 1711872000.0
    }
  ]
}
```

---

## Model Registry

Models are stored on disk in a structured directory hierarchy:

```
models/
├── fraud-gbm/
│   └── 1/
│       ├── model.onnx          # ONNX model file
│       └── metadata.json       # Version metadata
└── anomaly-iforest/
    └── 1/
        └── metadata.json       # Heuristic-only (no ONNX file)
```

### metadata.json

```json
{
  "description": "Gradient boosted model trained on payment fraud data",
  "training_date": "2026-03-15",
  "auc": 0.94,
  "features": ["amount", "hour_of_day", "is_new_device", "is_vpn", "is_emulator",
               "is_bot", "transaction_count_24h", "distinct_countries_7d", "account_age_days"],
  "traffic_weight": 80,
  "active": true
}
```

| Field | Type | Description |
|---|---|---|
| `description` | string | Human-readable model description |
| `training_date` | string | ISO date when the model was trained |
| `auc` | float | Area under ROC curve (if applicable) |
| `features` | string[] | Ordered list of feature names the model expects |
| `traffic_weight` | int | Traffic weight for A/B routing (0–100) |
| `active` | bool | Whether this version receives traffic |

---

## A/B Testing

When multiple active versions exist for a model, the registry routes traffic probabilistically based on `traffic_weight`. Routing is **deterministic per tenant** — the same `tenant_id` always resolves to the same variant (using a SHA-256 hash seed) so results are consistent within a tenant.

**Example configuration:**

| Version | Traffic Weight | Receives |
|---|---|---|
| `fraud-gbm/v1` | 80 | ~80% of tenants |
| `fraud-gbm/v2` | 20 | ~20% of tenants |

To set up an A/B test:

1. Deploy the new model version to `models/fraud-gbm/2/`
2. Set `"traffic_weight": 20, "active": true` in its `metadata.json`
3. Adjust the existing version to `"traffic_weight": 80`
4. The registry picks up changes on scan

To end the test and roll out the winner:

```bash
curl -X POST http://localhost:8005/v1/models/fraud-gbm/activate \
  -H "Content-Type: application/json" \
  -d '{"version": 2}'
```

---

## Feature Vector

The ML Scoring service expects a 9-element feature vector. Features are extracted from the `features` dict in the score request, normalized, and fed to the model.

| Index | Feature | Normalization | Description |
|---|---|---|---|
| 0 | `amount` | ÷ 10,000 | Transaction amount |
| 1 | `hour_of_day` | ÷ 24 | Hour of the event (0–23) |
| 2 | `is_new_device` | 0/1 | First time seeing this device (alias: `new_device`) |
| 3 | `is_vpn` | 0/1 | VPN detected |
| 4 | `is_emulator` | 0/1 | Emulator/simulator detected |
| 5 | `is_bot` | 0/1 | Bot behavior detected |
| 6 | `transaction_count_24h` | ÷ 100 | Number of transactions in last 24 hours |
| 7 | `distinct_countries_7d` | ÷ 10 | Distinct countries in last 7 days |
| 8 | `account_age_days` | ÷ 365 | Account age in days |

---

## Heuristic Scoring

When no ONNX model is loaded (or as a fallback), the service uses a heuristic scoring function:

| Condition | Score Delta |
|---|---|
| Base score | +10 |
| `amount` > 5,000 | +15 |
| `amount` > 15,000 | +20 |
| `amount` > 50,000 | +10 |
| `is_new_device` = true | +10 |
| `is_emulator` = true | +15 |
| `is_bot` = true | +20 |
| `is_vpn` = true | +5 |
| `hour_of_day` 0–5 or ≥ 22 | +8 |
| `transaction_count_24h` > 20 | +10 |
| `transaction_count_24h` > 10 | +5 |
| `distinct_countries_7d` ≥ 4 | +10 |
| `distinct_countries_7d` ≥ 2 | +3 |
| `account_age_days` < 7 | +12 |
| `account_age_days` < 30 | +5 |

Final score is clamped to 0–100.

---

## Training Pipeline

The repository includes a training pipeline in `services/ml-scoring/training/`.

### Generate Sample Data

```bash
cd services/ml-scoring/training
pip install -r requirements.txt
python generate_sample_data.py
```

This creates a synthetic fraud dataset with the 9 features above.

### Train a Model

```bash
python train_anomaly_model.py
```

This trains an Isolation Forest anomaly detection model and exports it to ONNX format.

### Deploy a Model

1. Create a version directory:
   ```bash
   mkdir -p models/my-model/1
   ```

2. Copy your ONNX model:
   ```bash
   cp trained_model.onnx models/my-model/1/model.onnx
   ```

3. Create `metadata.json`:
   ```json
   {
     "description": "My custom fraud model",
     "training_date": "2026-03-31",
     "traffic_weight": 100,
     "active": true
   }
   ```

4. Restart the ML Scoring service (or it will pick up models on next scan).

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DISABLE_ML` | `false` | Set to `true` to disable ML scoring entirely (returns score 0) |
| `ML_MODEL_VERSION` | `heuristic-v1` | Default model version label for legacy ONNX path |
| `ONNX_MODEL_PATH` | _(empty)_ | Direct path to a single ONNX file (legacy, use registry instead) |
| `MODELS_DIR` | `./models` | Directory containing the model registry |
| `API_KEYS` | _(empty)_ | Comma-separated API keys. Empty = no auth |
