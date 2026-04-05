FROM python:3.12-slim

# Debian security updates (ncurses, zlib, etc.) — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/decision-api/pyproject.toml /app/
COPY services/decision-api/alembic.ini /app/
COPY services/decision-api/alembic /app/alembic
COPY services/decision-api/src /app/src
COPY services/decision-api/rules /app/rules
COPY services/decision-api/static /app/static
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV RULES_PATH=/app/rules
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "decision_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
