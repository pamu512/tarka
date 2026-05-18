# Build context: repository root.
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY legacy_attic/services/ml_sidecar/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY legacy_attic/services/ml_sidecar/main.py services/ml_sidecar/onnx_engine.py ./
RUN mkdir -p /app/models

# Mount ``./services/ml_sidecar/models`` at runtime (place ``baseline_fraud_v1.onnx`` there).
CMD ["python", "-u", "main.py"]
