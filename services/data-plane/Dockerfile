FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/data-plane/pyproject.toml /app/
COPY services/event-ingest/event_ingest /app/event_ingest
COPY services/analytics-sink/analytics_sink /app/analytics_sink
COPY services/data-plane/data_plane /app/data_plane
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app:/app/shared
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
