FROM python:3.12-slim

# Debian security updates (ncurses, zlib, etc.) — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/decision-api/pyproject.toml /app/
COPY services/rule-engine /app/rule-engine
COPY services/shared /app/shared
SHELL ["/bin/bash", "-euxo", "pipefail", "-c"]
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && source "$HOME/.cargo/env" \
    && pip install --no-cache-dir "maturin>=1.7,<2.0" \
    && cd /app/rule-engine && maturin build --release \
    && pip install --no-cache-dir /app/rule-engine/target/wheels/tarka_rule_engine-*.whl \
    && rm -rf "$HOME/.cargo/registry" "$HOME/.cargo/git" /app/rule-engine/target
SHELL ["/bin/sh", "-c"]
COPY services/decision-api/alembic.ini /app/
COPY services/decision-api/alembic /app/alembic
COPY services/decision-api/src /app/src
COPY services/decision-api/rules /app/rules
COPY services/decision-api/static /app/static
RUN sed -i 's|file:../rule-engine|file:./rule-engine|g' /app/pyproject.toml \
    && pip install --no-cache-dir -e .
ENV RULES_PATH=/app/rules
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "decision_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
