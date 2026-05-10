FROM python:3.12-slim

# Debian security updates (ncurses, zlib, etc.) — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/decision-api
RUN pip install --no-cache-dir pip -U
COPY services/core /repo/services/core
COPY services/analytics /repo/services/analytics
COPY services/decision-api/pyproject.toml /repo/services/decision-api/
COPY services/shared /repo/services/shared
COPY services/decision-api/alembic.ini /repo/services/decision-api/
COPY services/decision-api/alembic /repo/services/decision-api/alembic
COPY services/decision-api/src /repo/services/decision-api/src
COPY services/decision-api/rules /repo/services/decision-api/rules
COPY services/decision-api/static /repo/services/decision-api/static
RUN pip install --no-cache-dir -e . \
    && rm -rf /root/.cache /root/.cargo/registry /root/.cargo/git 2>/dev/null || true
ENV RULES_PATH=/repo/services/decision-api/rules
ENV PYTHONPATH=/repo/services/decision-api/src:/repo/services/shared
CMD ["uvicorn", "decision_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
