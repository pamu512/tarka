FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY legacy_attic/services/graph-service/pyproject.toml /app/
COPY legacy_attic/services/graph-service/src /app/src
COPY legacy_attic/services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "graph_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
