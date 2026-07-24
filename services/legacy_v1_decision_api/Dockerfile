FROM python:3.12-slim AS rule-engine-builder

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && . "$HOME/.cargo/env" \
    && pip install --no-cache-dir maturin
ENV PATH="/root/.cargo/bin:${PATH}"
WORKDIR /build
COPY services/rule-engine /build/rule-engine
RUN cd /build/rule-engine && maturin build --release --out /wheels

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
COPY services/legacy_v1_decision_api/pyproject.toml /repo/services/decision-api/
COPY services/shared /repo/services/shared
COPY services/legacy_v1_decision_api/alembic.ini /repo/services/decision-api/
COPY services/legacy_v1_decision_api/alembic /repo/services/decision-api/alembic
COPY services/legacy_v1_decision_api/src /repo/services/decision-api/src
COPY services/legacy_v1_decision_api/rules /repo/services/decision-api/rules
COPY services/legacy_v1_decision_api/static /repo/services/decision-api/static
COPY --from=rule-engine-builder /wheels /wheels
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels /root/.cache /root/.cargo/registry /root/.cargo/git 2>/dev/null || true
ENV RULES_PATH=/repo/services/decision-api/rules
ENV PYTHONPATH=/repo/services/decision-api/src:/repo/services/shared
ENV TARKA_JSON_RULES_ENGINE=rust
CMD ["uvicorn", "decision_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
