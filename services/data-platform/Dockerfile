FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/data-platform/pyproject.toml /app/
COPY services/data-platform/src /app/src
COPY services/shared /app/shared
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared:/app/packages/shared-core
CMD ["uvicorn", "data_platform.main:app", "--host", "0.0.0.0", "--port", "8014"]
