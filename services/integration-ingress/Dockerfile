FROM python:3.12-slim

# Debian security updates — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/integration-ingress
RUN pip install --no-cache-dir pip -U
COPY infra/deploy/constraints.txt /tmp/constraints.txt
COPY services/core /repo/services/core
COPY services/integration-ingress/pyproject.toml /repo/services/integration-ingress/
COPY services/integration-ingress/alembic.ini /repo/services/integration-ingress/
COPY services/integration-ingress/alembic /repo/services/integration-ingress/alembic
COPY services/integration-ingress/src /repo/services/integration-ingress/src
COPY services/shared /repo/services/shared
RUN sed -i \
        -e 's|file:../core|file:/repo/services/core|g' \
        /repo/services/integration-ingress/pyproject.toml \
    && pip install --no-cache-dir -c /tmp/constraints.txt -e .
ENV PYTHONPATH=/repo/services/integration-ingress/src:/repo/services/shared
# First boot / ops contexts run migrations; compose sets TARKA_SKIP_STARTUP_MIGRATIONS=1
# (same contract as case-api) so routine restarts never execute DDL unconditionally.
CMD ["/bin/sh", "-c", "if [ \"$(echo \"$TARKA_SKIP_STARTUP_MIGRATIONS\" | tr '[:upper:]' '[:lower:]')\" != \"1\" ]; then alembic upgrade head; fi; exec uvicorn integration_ingress.main:app --host 0.0.0.0 --port 8003"]
