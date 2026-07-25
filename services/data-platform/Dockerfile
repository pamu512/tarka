FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir pip -U
<<<<<<< HEAD
COPY services/data-plane/src/data_plane /app/data_plane
COPY services/shared /app/shared
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.6.0" \
    "redis[hiredis]>=5.2.0" \
    "asyncpg>=0.29.0" \
    "structlog>=24.1.0"
ENV PYTHONPATH=/app:/app/shared
# Compatibility listener: same app as data_plane.platform, port 8014 contract.
CMD ["uvicorn", "data_plane.platform.app:app", "--host", "0.0.0.0", "--port", "8014"]
=======
COPY services/data-platform/pyproject.toml /app/
COPY services/data-platform/src /app/src
COPY services/shared /app/shared
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared:/app/packages/shared-core
CMD ["uvicorn", "data_platform.main:app", "--host", "0.0.0.0", "--port", "8014"]
>>>>>>> origin/master
