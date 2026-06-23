FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/data-platform/pyproject.toml /app/
COPY services/data-platform /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app:/app/shared
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8014"]

