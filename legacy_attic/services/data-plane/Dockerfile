FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY legacy_attic/services/data-plane/pyproject.toml /app/
COPY legacy_attic/services/event-ingest/src/event_ingest /app/src/event_ingest
COPY legacy_attic/services/analytics-sink/src/analytics_sink /app/src/analytics_sink
COPY legacy_attic/services/data-plane/src/data_plane /app/src/data_plane
COPY legacy_attic/services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "data_plane.main:app", "--host", "0.0.0.0", "--port", "8007"]
