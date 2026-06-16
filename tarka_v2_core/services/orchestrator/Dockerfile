# Context directory: repository root
#   docker build -f tarka_v2_core/services/orchestrator/Dockerfile -t tarka-orchestrator:dev .

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1: install wheels into /install (builder uses full Alpine + toolchain).
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-alpine AS builder

WORKDIR /build/tarka_v2_core

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache build-base

COPY packages/tarka-deploy-settings ../packages/tarka-deploy-settings
COPY tarka_v2_core/services/orchestrator/pyproject.toml tarka_v2_core/services/orchestrator/README.md tarka_v2_core/services/orchestrator/requirements.txt ./services/orchestrator/
COPY tarka_v2_core/services/orchestrator/src ./services/orchestrator/src
COPY tarka_v2_core/services/ingestor/src ./services/ingestor/src
COPY tarka_v2_core/services/rule_engine/pyproject.toml tarka_v2_core/services/rule_engine/README.md ./services/rule_engine/
COPY tarka_v2_core/services/rule_engine/src ./services/rule_engine/src

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefix=/install --no-cache-dir ./services/rule_engine \
    && python -m pip install --prefix=/install --no-cache-dir ./services/orchestrator \
    && python -m pip install --prefix=/install --no-cache-dir -r ./services/orchestrator/requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: minimal runtime (non-root).
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-alpine AS runtime

WORKDIR /app

ENV PYTHONPATH=/app/services/ingestor/src:/app/services/shared:/app/services/rule_engine/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache libstdc++ \
    && addgroup -g 10001 -S tarka \
    && adduser -S -D -H -u 10001 -G tarka -s /sbin/nologin tarka

COPY --from=builder /install/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages

COPY tarka_v2_core/services/ingestor/src ./services/ingestor/src
COPY tarka_v2_core/services/rule_engine/src ./services/rule_engine/src
COPY tarka_v2_core/services/shared/tarka_shared ./services/shared/tarka_shared

USER tarka

EXPOSE 8790

ENTRYPOINT ["/usr/local/bin/python3", "-m", "uvicorn"]
CMD ["orchestrator.main:app", "--host", "0.0.0.0", "--port", "8790"]
