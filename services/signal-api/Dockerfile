FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/signal-api/pyproject.toml /app/
COPY services/feature-service/src/feature_service /app/src/feature_service
COPY services/ml-scoring/src/ml_scoring /app/src/ml_scoring
COPY services/calibration-service/src/calibration_service /app/src/calibration_service
COPY services/counter-service/src/counter_service /app/src/counter_service
COPY services/location-service/src/location_service /app/src/location_service
COPY services/signal-api/src/signal_api /app/src/signal_api
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "signal_api.main:app", "--host", "0.0.0.0", "--port", "8004"]
