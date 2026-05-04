FROM python:3.12-slim

# Debian security updates — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/integration-ingress
RUN pip install --no-cache-dir pip -U
COPY services/core /repo/services/core
COPY services/integration-ingress/pyproject.toml /repo/services/integration-ingress/
COPY services/integration-ingress/alembic.ini /repo/services/integration-ingress/
COPY services/integration-ingress/alembic /repo/services/integration-ingress/alembic
COPY services/integration-ingress/src /repo/services/integration-ingress/src
COPY services/shared /repo/services/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/repo/services/integration-ingress/src:/repo/services/shared
CMD ["uvicorn", "integration_ingress.main:app", "--host", "0.0.0.0", "--port", "8003"]
