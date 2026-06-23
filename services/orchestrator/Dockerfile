# Context directory: repository root
#   docker build -f services/orchestrator/Dockerfile -t tarka-orchestrator:dev .

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY packages/deploy-settings /packages/deploy-settings
COPY services/orchestrator/pyproject.toml services/orchestrator/README.md services/orchestrator/requirements.txt ./services/orchestrator/
COPY services/orchestrator ./services/orchestrator
COPY services/ingestor ./services/ingestor
COPY services/rule_engine/pyproject.toml services/rule_engine/README.md ./services/rule_engine/
COPY services/rule_engine ./services/rule_engine

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefix=/install --no-cache-dir ./services/rule_engine \
    && python -m pip install --prefix=/install --no-cache-dir ./services/orchestrator \
    && python -m pip install --prefix=/install --no-cache-dir -r ./services/orchestrator/requirements.txt

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

WORKDIR /app/services/orchestrator

ENV PYTHONPATH=/app/services/orchestrator:/app/services:/app/services/rule_engine:/app/packages/shared-core \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 tarka \
    && useradd -r -u 10001 -g tarka -s /usr/sbin/nologin tarka

COPY --from=builder /install/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages

COPY services/orchestrator /app/services/orchestrator
COPY services/ingestor /app/services/ingestor
COPY services/rule_engine /app/services/rule_engine
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared

USER tarka

EXPOSE 8790

ENTRYPOINT ["/usr/local/bin/python3", "-m", "uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8790"]
