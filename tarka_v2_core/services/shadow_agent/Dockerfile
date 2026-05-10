# Context directory: `tarka_v2_core/`
#   docker build -f services/shadow_agent/Dockerfile -t tarka-shadow-agent:dev .

FROM python:3.12-alpine AS builder

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache build-base

COPY services/shadow_agent/pyproject.toml services/shadow_agent/README.md ./services/shadow_agent/
COPY services/shadow_agent/src ./services/shadow_agent/src
COPY services/ingestor/src ./services/ingestor/src
COPY services/shared/tarka_shared ./services/shared/tarka_shared

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefix=/install --no-cache-dir "./services/shadow_agent" \
    && python -m pip install --prefix=/install --no-cache-dir "openai>=1.50.0"

FROM python:3.12-alpine AS runtime

WORKDIR /app

ENV PYTHONPATH=/app/services/ingestor/src:/app/services/shared \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache libstdc++ \
    && addgroup -g 10001 -S tarka \
    && adduser -S -D -H -u 10001 -G tarka -s /sbin/nologin tarka

COPY --from=builder /install/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages

COPY services/ingestor/src ./services/ingestor/src
COPY services/shared/tarka_shared ./services/shared/tarka_shared

USER tarka

EXPOSE 8801

ENTRYPOINT ["/usr/local/bin/python3", "-m", "uvicorn"]
CMD ["shadow_agent.main:app", "--host", "0.0.0.0", "--port", "8801"]
