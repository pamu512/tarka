# Context directory: repository root
#   docker build -f services/rule_engine/Dockerfile -t tarka-rule-engine:dev .

FROM python:3.12-alpine AS builder

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache build-base

COPY packages/deploy-settings /packages/deploy-settings
COPY services/rule_engine/pyproject.toml services/rule_engine/README.md ./services/rule_engine/
COPY services/rule_engine ./services/rule_engine
COPY services/ingestor ./services/ingestor
COPY packages/shared-core/tarka_shared ./packages/shared-core/tarka_shared

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefix=/install --no-cache-dir ./services/rule_engine

FROM python:3.12-alpine AS runtime

WORKDIR /app/services/rule_engine

ENV PYTHONPATH=/app/services/rule_engine:/app/services:/app/packages/shared-core \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache libstdc++ \
    && addgroup -g 10001 -S tarka \
    && adduser -S -D -H -u 10001 -G tarka -s /sbin/nologin tarka

COPY --from=builder /install/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages

COPY services/rule_engine /app/services/rule_engine
COPY services/ingestor /app/services/ingestor
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared

USER tarka

EXPOSE 8778

ENTRYPOINT ["/usr/local/bin/python3", "-m", "uvicorn"]
CMD ["main:create_app", "--host", "0.0.0.0", "--port", "8778", "--factory"]
