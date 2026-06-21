FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/core /app/core
RUN pip install --no-cache-dir -e /app/core
COPY services/signal-api/pyproject.toml /app/
COPY services/feature-service/feature_service /app/feature_service
COPY services/ml-scoring/ml_scoring /app/ml_scoring
COPY services/calibration-service/calibration_service /app/calibration_service
COPY services/counter-service/counter_service /app/counter_service
COPY services/location-service/location_service /app/location_service
COPY services/signal-api/signal_api /app/signal_api
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app:/app/shared
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
