FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
# Local path deps in pyproject.toml (file:../core, file:../analytics) must exist before `pip install`;
# sed below rewrites them to file:./core and file:./analytics under WORKDIR.
COPY legacy_attic/services/core /app/core
COPY legacy_attic/services/analytics /app/analytics
COPY legacy_attic/services/shared /app/shared
COPY legacy_attic/services/core-api/pyproject.toml /app/
COPY legacy_attic/services/legacy_v1_decision_api/src/decision_api /app/src/decision_api
COPY legacy_attic/services/legacy_v1_decision_api/alembic /app/decision_migrations
COPY legacy_attic/services/legacy_v1_decision_api/rules /app/rules
COPY legacy_attic/services/legacy_v1_decision_api/static /app/static
COPY legacy_attic/services/case-api/src/case_api /app/src/case_api
COPY legacy_attic/services/case-api/static /app/case-api/static
COPY legacy_attic/services/case-api/alembic /app/case_migrations
COPY legacy_attic/services/core-api/src/core_api /app/src/core_api
COPY legacy_attic/services/core-api/config/decision_alembic.ini /app/config/decision_alembic.ini
COPY legacy_attic/services/core-api/config/case_alembic.ini /app/config/case_alembic.ini
RUN sed -i \
    -e 's|file:../core|file:./core|g' \
    -e 's|file:../analytics|file:./analytics|g' \
    /app/pyproject.toml \
    && pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
ENV RULES_PATH=/app/rules
CMD ["/bin/sh", "-c", "alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head && exec uvicorn core_api.main:app --host 0.0.0.0 --port 8000"]
