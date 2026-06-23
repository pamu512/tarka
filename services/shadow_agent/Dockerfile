# Context directory: repository root
#   docker build -f services/shadow_agent/Dockerfile -t tarka-shadow-agent:dev .

FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY packages/deploy-settings /packages/deploy-settings
COPY services/shadow_agent/pyproject.toml services/shadow_agent/README.md ./services/shadow_agent/
COPY services/shadow_agent ./services/shadow_agent
COPY services/ingestor ./services/ingestor
COPY packages/shared-core/tarka_shared ./packages/shared-core/tarka_shared

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefix=/install --no-cache-dir "./services/shadow_agent" \
    && python -m pip install --prefix=/install --no-cache-dir "openai>=1.50.0"

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app/services/shadow_agent

ENV PYTHONPATH=/app/services/shadow_agent:/app/services:/app/packages/shared-core \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 tarka \
    && useradd -r -u 10001 -g tarka -s /usr/sbin/nologin tarka

COPY --from=builder /install/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages

COPY services/shadow_agent /app/services/shadow_agent
COPY services/ingestor /app/services/ingestor
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared

USER tarka

EXPOSE 8801

ENTRYPOINT ["/usr/local/bin/python3", "-m", "uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8801"]
