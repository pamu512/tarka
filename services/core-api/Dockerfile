FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Base image / ensurepip often ship vulnerable setuptools+msgpack; force-replace for Trivy.
RUN pip install --no-cache-dir -U pip wheel \
    && pip uninstall -y setuptools msgpack || true \
    && pip install --no-cache-dir "setuptools>=83.0.0" "msgpack>=1.2.1" \
    && rm -rf /usr/local/lib/python*/ensurepip/_bundled/setuptools*.whl \
              /usr/local/lib/python*/ensurepip/_bundled/wheel*.whl || true
# Local path deps in pyproject.toml (file:../core, file:../analytics) must exist before `pip install`;
# sed below rewrites them to file:./core and file:./analytics under WORKDIR.
COPY services/core /app/core
COPY services/analytics /app/analytics
COPY services/shared /app/shared
COPY adapters /app/adapters
COPY services/core-api/pyproject.toml /app/
COPY services/decision-api/src/decision_api /app/decision_api
COPY services/decision-api/alembic /app/decision_migrations
COPY services/decision-api/rules /app/rules
COPY services/decision-api/static /app/static
COPY services/case-api/src/case_api /app/case_api
COPY services/case-api/static /app/case-api/static
COPY services/case-api/alembic /app/case_migrations
COPY services/core-api/src /app/src
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared
COPY services/core-api/config/decision_alembic.ini /app/config/decision_alembic.ini
COPY services/core-api/config/decision_alembic.ini /app/alembic.ini
COPY services/core-api/config/case_alembic.ini /app/config/case_alembic.ini
RUN sed -i -e 's|file:../core|file:/app/core|g' /app/analytics/pyproject.toml \
    && sed -i \
        -e 's|file:../core|file:/app/core|g' \
        -e 's|file:../analytics|file:/app/analytics|g' \
        /app/pyproject.toml \
    && pip install --no-cache-dir -e . \
    && pip uninstall -y setuptools msgpack || true \
    && pip install --no-cache-dir "setuptools>=83.0.0" "msgpack>=1.2.1" \
    && python -c "import importlib.metadata as m; s=m.version('setuptools'); p=m.version('msgpack'); assert tuple(int(x) for x in s.split('.')[:2])>=(83,0), s; assert tuple(int(x) for x in p.split('.')[:2])>=(1,2), p; print('setuptools', s, 'msgpack', p)"
ENV PYTHONPATH=/app/src:/app:/app/shared:/app/packages/shared-core
ENV RULES_PATH=/app/rules
CMD ["/bin/sh", "-c", "alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head && exec uvicorn core_api.main:app --host 0.0.0.0 --port 8000"]
