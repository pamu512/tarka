# How to plug in your own ONNX model

**Service:** `services/ml-scoring`  
**Runtime:** `onnxruntime` (optional dependency — install with `pip install -e ".[onnx]"` from `services/ml-scoring`).

## Environment variables

| Variable | Purpose |
|----------|---------|
| **`ONNX_MODEL_PATH`** | Absolute path inside the container or host to a `.onnx` file. When set and **`DISABLE_ML`** is not true, the service loads this model at startup. |
| **`ML_MODEL_VERSION`** | Logical version string returned in responses (e.g. `fraud-onnx-v3`). |
| **`MODELS_DIR`** | Directory for **`ModelRegistry`** metadata (canary / approve flows). Defaults to `services/ml-scoring/models`. |
| **`DISABLE_ML`** | If `true`, skips ONNX and uses heuristics only. |

## Input contract

The scoring path builds a **feature vector** from the request using **`_FEATURE_ORDER`** in `ml_scoring/main.py` (`amount`, `hour_of_day`, `is_new_device`, …). Your ONNX model’s **first input** should accept a tensor whose shape matches what the code feeds (see `_onnx_predict` in `main.py`). If your feature order differs, either:

- Map your training schema into the existing keys in the **`ScoreRequest.features`** dict, **or**
- Extend **`_FEATURE_ORDER`** and document the breaking change in release notes.

## Docker

Mount the model and set env in compose or Helm values, for example:

```yaml
environment:
  ONNX_MODEL_PATH: /models/fraud.onnx
  ML_MODEL_VERSION: custom-v1
volumes:
  - ./my-models:/models:ro
```

Rebuild or install **`onnxruntime`** in the image (add to Dockerfile `pip install onnxruntime` or use optional extra).

## Decision API wiring

Point **Decision API** at ML scoring with **`ML_SCORING_URL`** (e.g. `http://ml-scoring:8005`). The Decision API merges ML output into scores and audit payloads per existing orchestration.

## Testing

Use **`services/ml-scoring/tests/`** as templates. For integration smoke, `POST /v1/score` (or the route your version exposes) with a minimal feature dict and assert HTTP 200 and stable latency.
