FROM python:3.12-slim

# Debian security updates — reduces Trivy HIGH/MEDIUM on base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/decision-api
RUN pip install --no-cache-dir -U pip wheel \
    && pip uninstall -y setuptools msgpack || true \
    && pip install --no-cache-dir "setuptools>=83.0.0" "msgpack>=1.2.1" \
    && rm -rf /usr/local/lib/python*/ensurepip/_bundled/setuptools*.whl \
              /usr/local/lib/python*/ensurepip/_bundled/wheel*.whl \
    && rm -f /usr/local/lib/python*/site-packages/pip/_vendor/bom.cdx.json \
    && find /usr/local/lib -path '*/pip/_vendor/vendor.txt' -exec sed -i -E '/^(setuptools|msgpack)==/d' {} + \
    || true
COPY services/core /repo/services/core
COPY services/analytics /repo/services/analytics
COPY services/decision-api/pyproject.toml /repo/services/decision-api/
COPY services/shared /repo/services/shared
COPY services/decision-api/alembic.ini /repo/services/decision-api/
COPY services/decision-api/alembic /repo/services/decision-api/alembic
COPY services/decision-api/src /repo/services/decision-api/src
COPY services/decision-api/rules /repo/services/decision-api/rules
COPY services/decision-api/static /repo/services/decision-api/static
COPY adapters /repo/adapters
RUN pip install --no-cache-dir -e . \
    && pip uninstall -y setuptools msgpack || true \
    && pip install --no-cache-dir "setuptools>=83.0.0" "msgpack>=1.2.1" \
    && rm -f /usr/local/lib/python*/site-packages/pip/_vendor/bom.cdx.json \
    && find /usr/local/lib -path '*/pip/_vendor/vendor.txt' -exec sed -i -E '/^(setuptools|msgpack)==/d' {} + \
    && python -c "import importlib.metadata as m; s=m.version('setuptools'); p=m.version('msgpack'); assert tuple(int(x) for x in s.split('.')[:2])>=(83,0), s; assert tuple(int(x) for x in p.split('.')[:2])>=(1,2), p" \
    && rm -rf /root/.cache /root/.cargo/registry /root/.cargo/git 2>/dev/null || true
ENV RULES_PATH=/repo/services/decision-api/rules
ENV PYTHONPATH=/repo/services/decision-api/src:/repo/services/shared:/repo
CMD ["uvicorn", "decision_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
