FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
# Local path deps in pyproject.toml (file:../core, file:../analytics) must exist before `pip install`;
# sed below rewrites them to file:./core and file:./analytics under WORKDIR.
COPY services/core /app/core
COPY services/analytics /app/analytics
COPY services/shared /app/shared
COPY services/core-api/main.py /app/main.py
COPY services/core-api/pyproject.toml /app/
COPY services/legacy_v1_decision_api/src/decision_api /app/decision_api
COPY services/decision-api/src/decision_api/benchmark_export_api.py /app/decision_api/benchmark_export_api.py
COPY services/decision-api/src/decision_api/drift_query_api.py /app/decision_api/drift_query_api.py
COPY services/legacy_v1_decision_api/alembic /app/decision_migrations
COPY services/legacy_v1_decision_api/rules /app/rules
COPY services/legacy_v1_decision_api/static /app/static
COPY services/case-api/src/case_api /app/case_api
COPY services/case-api/static /app/case-api/static
COPY services/case-api/alembic /app/case_migrations
COPY services/core-api/src/core_api /app/core_api
COPY services/core-api/config/decision_alembic.ini /app/config/decision_alembic.ini
COPY services/core-api/config/decision_alembic.ini /app/alembic.ini
COPY services/core-api/config/case_alembic.ini /app/config/case_alembic.ini
RUN sed -i -e 's|file:../core|file:/app/core|g' /app/analytics/pyproject.toml \
    && sed -i \
        -e 's|file:../core|file:/app/core|g' \
        -e 's|file:../analytics|file:/app/analytics|g' \
        /app/pyproject.toml \
    && pip install --no-cache-dir -e .
ENV PYTHONPATH=/app:/app/shared:/app/case_api:/app/decision_api
ENV RULES_PATH=/app/rules
CMD ["/bin/sh", "-c", "alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
