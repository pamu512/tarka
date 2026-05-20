FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY legacy_attic/services/data-platform/pyproject.toml /app/
COPY legacy_attic/services/data-platform/src /app/src
COPY legacy_attic/services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "data_platform.main:app", "--host", "0.0.0.0", "--port", "8014"]

