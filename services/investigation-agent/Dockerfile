FROM python:3.12-slim

# Debian security updates — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/investigation-agent/pyproject.toml /app/
COPY services/investigation-agent/src /app/src
COPY services/collaboration-chat-bridge /app/collaboration-chat-bridge
COPY services/shared /app/shared
COPY packages/shared-core/pyproject.toml /app/packages/shared-core/
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -e /app/packages/shared-core \
    && pip install --no-cache-dir -e /app/collaboration-chat-bridge
ENV PYTHONPATH=/app/src:/app/shared:/app/packages/shared-core
CMD ["uvicorn", "investigation_agent.main:app", "--host", "0.0.0.0", "--port", "8006"]
