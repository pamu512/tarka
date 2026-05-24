FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/case-api
RUN pip install --no-cache-dir pip -U
COPY legacy_attic/services/core /repo/services/core
COPY legacy_attic/services/case-api/pyproject.toml /repo/services/case-api/
COPY legacy_attic/services/case-api/alembic.ini /repo/services/case-api/
COPY legacy_attic/services/case-api/alembic /repo/services/case-api/alembic
COPY legacy_attic/services/case-api/src /repo/services/case-api/src
COPY legacy_attic/services/shared /repo/services/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/repo/services/case-api/src:/repo/services/shared
CMD ["uvicorn", "case_api.main:app", "--host", "0.0.0.0", "--port", "8002"]
