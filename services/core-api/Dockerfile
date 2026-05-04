FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/core-api/pyproject.toml /app/
COPY services/decision-api/src/decision_api /app/src/decision_api
COPY services/decision-api/alembic /app/decision_migrations
COPY services/decision-api/rules /app/rules
COPY services/decision-api/static /app/static
COPY services/case-api/src/case_api /app/src/case_api
COPY services/case-api/alembic /app/case_migrations
COPY services/case-api/static /app/case-api/static
COPY services/core-api/src/core_api /app/src/core_api
COPY services/core-api/config/decision_alembic.ini /app/config/decision_alembic.ini
COPY services/core-api/config/case_alembic.ini /app/config/case_alembic.ini
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
ENV RULES_PATH=/app/rules
CMD ["/bin/sh", "-c", "alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head && exec uvicorn core_api.main:app --host 0.0.0.0 --port 8000"]
