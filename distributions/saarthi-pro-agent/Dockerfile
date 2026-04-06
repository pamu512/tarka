# Saarthi Pro — standalone investigation agent image
# Build from the fraud-stack repository root (not this directory):
#
#   docker build -f distributions/saarthi-pro-agent/Dockerfile \
#     --build-arg SAARTHI_PRO_VERSION=0.1.0 \
#     --build-arg FRAUD_STACK_GIT_SHA="$(git rev-parse HEAD)" \
#     --build-arg INTEGRATION_CONTRACT_VERSION=1.1.0 \
#     -t saarthi-pro-agent:0.1.0 .
#
# Windows (PowerShell): see scripts/build_saarthi_pro_agent_image.ps1

FROM python:3.12-slim

ARG SAARTHI_PRO_VERSION=0.0.0-dev
ARG FRAUD_STACK_GIT_SHA=unknown
ARG INTEGRATION_CONTRACT_VERSION=1.1.0

LABEL org.opencontainers.image.title="Saarthi Pro Investigation Agent"
LABEL org.opencontainers.image.description="Investigation copilot; built from Tarka fraud-stack investigation-agent + shared"
LABEL org.opencontainers.image.version="${SAARTHI_PRO_VERSION}"
LABEL com.saarthi.pro.version="${SAARTHI_PRO_VERSION}"
LABEL com.tarka.fraud_stack.git_sha="${FRAUD_STACK_GIT_SHA}"
LABEL com.tarka.integration_contract_version="${INTEGRATION_CONTRACT_VERSION}"

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/investigation-agent/pyproject.toml /app/
COPY services/investigation-agent/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
ENV AGENT_BUILD_ID=""
CMD ["uvicorn", "investigation_agent.main:app", "--host", "0.0.0.0", "--port", "8006"]
