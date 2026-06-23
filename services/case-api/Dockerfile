FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/case-api
RUN pip install --no-cache-dir pip -U
COPY services/core /repo/services/core
COPY services/case-api/pyproject.toml /repo/services/case-api/
COPY services/case-api/alembic.ini /repo/services/case-api/
COPY services/case-api/alembic /repo/services/case-api/alembic
COPY services/case-api /repo/services/case-api
COPY services/shared /repo/services/shared
COPY packages/shared-core /repo/packages/shared-core
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/repo/services/case-api/src:/repo/services/shared:/repo/packages/shared-core
CMD ["uvicorn", "case_api.main:app", "--host", "0.0.0.0", "--port", "8002"]
