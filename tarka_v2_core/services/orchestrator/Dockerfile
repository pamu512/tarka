# Context directory: `tarka_v2_core/`
#   docker build -f services/orchestrator/Dockerfile -t tarka-orchestrator:dev .

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1: install wheels into /install (builder uses full Alpine + toolchain).
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-alpine AS builder

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache build-base

COPY services/orchestrator/pyproject.toml services/orchestrator/README.md services/orchestrator/requirements.txt ./services/orchestrator/
COPY services/orchestrator/src ./services/orchestrator/src
COPY services/ingestor/src ./services/ingestor/src

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefix=/install --no-cache-dir ./services/orchestrator \
    && python -m pip install --prefix=/install --no-cache-dir -r ./services/orchestrator/requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: minimal runtime (non-root).
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-alpine AS runtime

WORKDIR /app

ENV PYTHONPATH=/app/services/ingestor/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache libstdc++ \
    && addgroup -g 10001 -S tarka \
    && adduser -S -D -H -u 10001 -G tarka -s /sbin/nologin tarka

COPY --from=builder /install/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages

COPY services/ingestor/src ./services/ingestor/src

USER tarka

EXPOSE 8790

ENTRYPOINT ["/usr/local/bin/python3", "-m", "uvicorn"]
CMD ["orchestrator.main:app", "--host", "0.0.0.0", "--port", "8790"]
